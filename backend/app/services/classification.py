"""Классификация находок рентгена ОГК и порождение находок-черновиков (FR-10, SR-1, SR-5, SR-7).

Поток:
  1. Гейт применимости (SR-7): вне диапазона — явный отказ, результат НЕ пишется.
  2. Модель выдаёт вероятность по каждому коду словаря находок.
  3. Все вероятности пишутся в inference_result (трассировка SR-5).
  4. Находка-черновик (source=model, PENDING) — только при вероятности не ниже
     порога, подобранного на валидации (model_version.operating_points).

Инварианты:
  - Код «без патологии» (CXR-000) находкой не становится: отсутствие черновиков не
    означает «норма», заключение о норме делает только врач (SR-1, SR-2).
  - Коды вне словаря и без порога игнорируются (модель не может «расширить» словарь).
  - Модель в SHADOW пишет результат с shadow_run=True — врачу он не показывается
    никогда, даже после продвижения модели (раздел 2, FR-10 п. 5).
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.imaging import Series, Study
from app.models.ml import (
    ConfirmationStatus,
    Finding,
    FindingSource,
    InferenceResult,
    ModelStatus,
    ModelVersion,
)
from app.services.applicability import check_applicability
from app.services.finding_vocabulary import CODING_SYSTEM, by_code
from app.services.segmentation import ApplicabilityRefused, _series_context

NORMAL_CODE = "CXR-000"


class WrongModelTask(Exception):
    """Модель другого типа (например, сегментация) передана в классификацию."""


@dataclass
class ClassificationOutput:
    probabilities: dict[str, float]
    preprocessing_params: dict = field(default_factory=dict)


class ClassificationModel(ABC):
    """Контракт классификатора находок: вероятность по коду словаря."""

    weights_hash: str

    @abstractmethod
    def predict(self, series_object_prefix: str) -> ClassificationOutput:
        raise NotImplementedError

    def explain(self, series_object_prefix: str, codes: list[str]) -> dict[str, list[list[float]]]:
        """Карта значимости по коду (кадр превью). По умолчанию — не поддерживается."""
        return {}


class StubClassificationModel(ClassificationModel):
    """Детерминированная заглушка без GPU и пикселей: для контура и тестов."""

    def __init__(self, codes: list[str], weights_hash: str = "stub-0") -> None:
        self._codes = codes
        self.weights_hash = weights_hash

    def predict(self, series_object_prefix: str) -> ClassificationOutput:
        probs = {}
        for code in self._codes:
            h = hashlib.sha256(f"{series_object_prefix}|{code}|{self.weights_hash}".encode()).hexdigest()
            probs[code] = round(int(h[:8], 16) / 0xFFFFFFFF, 4)
        return ClassificationOutput(probs, {"adapter": "stub"})

    def explain(self, series_object_prefix: str, codes: list[str]) -> dict[str, list[list[float]]]:
        from app.services.heatmap import stub_grid

        return {c: stub_grid(f"{series_object_prefix}|{c}|{self.weights_hash}") for c in codes}


class TorchCXRClassifier(ClassificationModel):  # pragma: no cover - нужен torch и веса
    """Адаптер весов, обученных `app.training` (DenseNet-121).

    Веса берутся из MEDVIZ_MODELS_DIR/<weights_hash>.pt; хеш файла сверяется с
    зарегистрированным — подменённые веса не запускаются (SR-5).
    `fetch_dicom(prefix) -> bytes` отдаёт обезличенный DICOM серии (из MinIO).
    """

    def __init__(self, weights_hash: str, models_dir: str, fetch_dicom) -> None:
        from pathlib import Path

        from app.training.model_card import weights_sha256

        path = Path(models_dir) / f"{weights_hash}.pt"
        if not path.exists():
            raise FileNotFoundError(f"Нет файла весов {path}")
        actual = weights_sha256(path)
        if actual != weights_hash:
            raise RuntimeError(f"Хеш весов не совпадает: {actual} != {weights_hash}")
        import torch
        from torchvision import models

        ckpt = torch.load(path, map_location="cpu")
        self.codes = ckpt["codes"]
        self.image_size = ckpt.get("image_size", 512)
        model = models.densenet121()
        model.classifier = torch.nn.Linear(model.classifier.in_features, len(self.codes))
        model.load_state_dict(ckpt["state_dict"])
        model.eval()
        self._model = model
        self._fetch = fetch_dicom
        self.weights_hash = weights_hash

    def predict(self, series_object_prefix: str) -> ClassificationOutput:
        import tempfile
        from pathlib import Path

        import torch
        from torchvision import transforms

        from app.training.train import IMAGENET_MEAN, IMAGENET_STD, load_grayscale

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "image.dcm"
            f.write_bytes(self._fetch(series_object_prefix))
            img = load_grayscale(f, self.image_size)
        tf = transforms.Compose([
            transforms.Grayscale(num_output_channels=3),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ])
        x = tf(img).unsqueeze(0)
        self._last = (series_object_prefix, x)
        with torch.no_grad():
            p = torch.sigmoid(self._model(x))[0].tolist()
        return ClassificationOutput(
            {c: float(v) for c, v in zip(self.codes, p, strict=True)},
            {"adapter": "densenet121", "image_size": self.image_size},
        )


    def explain(self, series_object_prefix: str, codes: list[str]) -> dict[str, list[list[float]]]:
        """Grad-CAM по последнему блоку признаков DenseNet (features → relu → классификатор)."""
        import torch

        prefix, x = getattr(self, "_last", (None, None))
        if prefix != series_object_prefix:
            self.predict(series_object_prefix)
            _, x = self._last
        out: dict[str, list[list[float]]] = {}
        feats = torch.relu(self._model.features(x)).detach().requires_grad_(True)
        logits = self._model.classifier(torch.nn.functional.adaptive_avg_pool2d(feats, 1).flatten(1))
        for code in codes:
            if code not in self.codes:
                continue
            (grad,) = torch.autograd.grad(logits[0, self.codes.index(code)], feats, retain_graph=True)
            weights = grad.mean(dim=(2, 3), keepdim=True)
            cam = torch.relu((weights * feats).sum(dim=1))[0]
            out[code] = cam.tolist()
        return out


@dataclass
class ClassificationOutcome:
    inference_result_id: uuid.UUID
    finding_ids: list[uuid.UUID]
    shadow_run: bool


def draft_codes(
    probabilities: dict[str, float], operating_points: dict, modality: str | None
) -> list[tuple[str, float, float]]:
    """Какие коды становятся черновиками: (код, вероятность, порог). Чистая функция."""
    out = []
    for code in sorted(operating_points):
        if code == NORMAL_CODE:
            continue
        concept = by_code(code)
        if concept is None or (modality and modality.upper() not in concept.modalities):
            continue
        p = probabilities.get(code)
        t = (operating_points.get(code) or {}).get("threshold")
        if p is None or t is None:
            continue
        if p >= t:
            out.append((code, float(p), float(t)))
    return out


def classify_series(
    db: Session,
    *,
    series: Series,
    model_version: ModelVersion,
    model: ClassificationModel,
    age_years: float | None = None,
    store_artifact=None,
) -> ClassificationOutcome:
    """store_artifact(key, png_bytes) -> ref — куда сохранить тепловые карты (MinIO).

    Карты строятся только для черновиков, которые увидит врач (не для теневого прогона).
    """
    if model_version.task != "classification":
        raise WrongModelTask(f"Модель {model_version.name} — {model_version.task}, а не classification")
    study = db.get(Study, series.study_id)

    decision = check_applicability(_series_context(series, study, age_years), model_version.applicability)
    if not decision.admitted:
        raise ApplicabilityRefused(decision.reasons)

    output = model.predict(series.object_prefix or series.series_instance_uid)
    shadow = model_version.status == ModelStatus.SHADOW
    drafts = draft_codes(output.probabilities, model_version.operating_points or {}, series.modality)

    inference = InferenceResult(
        series_id=series.id,
        model_version_id=model_version.id,
        preprocessing_params=output.preprocessing_params,
        metrics={
            "probabilities": {k: round(v, 4) for k, v in sorted(output.probabilities.items())},
            "drafted": [c for c, _, _ in drafts],
        },
        shadow_run=shadow,
    )
    db.add(inference)
    db.flush()

    heatmap_refs: dict[str, str] = {}
    if drafts and store_artifact is not None and not shadow:
        from app.services.heatmap import to_png

        prefix = series.object_prefix or series.series_instance_uid
        for code, grid in model.explain(prefix, [c for c, _, _ in drafts]).items():
            if grid and grid[0]:
                heatmap_refs[code] = store_artifact(f"{prefix}/heatmap_{model_version.id}_{code}.png", to_png(grid))

    finding_ids: list[uuid.UUID] = []
    for code, p, t in drafts:
        finding = Finding(
            series_id=series.id,
            inference_result_id=inference.id,
            coding_system=CODING_SYSTEM,
            code=code,
            label=by_code(code).label_ru,
            # Уверенность — служебная величина для врача; в текст заключения не идёт.
            measurements={"confidence": round(p, 4), "threshold": round(t, 4)},
            # Тепловая карта — подсказка «куда смотрела модель», не разметка и не измерение.
            coordinates={"heatmap_ref": heatmap_refs[code]} if code in heatmap_refs else None,
            source=FindingSource.MODEL,
            confirmation_status=ConfirmationStatus.PENDING,
        )
        db.add(finding)
        db.flush()
        finding_ids.append(finding.id)

    return ClassificationOutcome(inference.id, finding_ids, shadow)
