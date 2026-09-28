"""Адаптеры моделей сегментации (ТЗ, раздел 4: MONAI/TotalSegmentator/nnU-Net).

Абстракция отделяет оркестрацию (segmentation.py) от конкретной модели, чтобы
модель подключалась «как есть» и заменялась без изменения контура. Реальный
адаптер TotalSegmentator подключается на стенде с GPU; здесь он объявлен, но
тяжёлые зависимости импортируются лениво. Заглушка нужна для сборки контура и
тестов без GPU и без обращения к пиксельным данным.

Каждый адаптер обязан вернуть: маску (ссылка на артефакт), пер-структурную
статистику вокселей (для детерминированных измерений FR-6) и метаданные
трассировки (SR-5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class StructureResult:
    """Результат по одной структуре: воксельная статистика для измерений."""

    key: str                          # метка класса модели
    voxel_count: int
    extent_voxels: tuple[int, int, int] | None = None  # bbox по осям (для линейных)
    density_values: list[float] = field(default_factory=list)  # напр. HU внутри маски


@dataclass
class SegmentationOutput:
    mask_artifact_ref: str | None            # ключ маски в объектном хранилище
    structures: list[StructureResult]
    preprocessing_params: dict = field(default_factory=dict)
    extra_metrics: dict = field(default_factory=dict)
    # Шаг сетки маски (мм) — если адаптер его знает, измерения считаются по нему.
    spacing_mm: tuple[float, float, float] | None = None


class SegmentationModel(ABC):
    """Контракт модели сегментации."""

    name: str
    semver: str
    weights_hash: str

    @abstractmethod
    def infer(self, series_object_prefix: str, spacing: tuple[float, float, float]) -> SegmentationOutput:
        """Выполнить сегментацию серии. Детерминированно при фиксированных весах."""
        raise NotImplementedError


# Структуры каталога, собираемые из нескольких классов TotalSegmentator.
TS_GROUPS: dict[str, tuple[str, ...]] = {
    "vertebrae_thoracic": tuple(f"vertebrae_T{i}" for i in range(1, 13)),
    "vertebrae_lumbar": tuple(f"vertebrae_L{i}" for i in range(1, 6)),
}


def labelmap_structures(labelmap, class_names: dict[int, str], keys: list[str]) -> list[StructureResult]:
    """Мультиметочная маска → воксельная статистика по структурам каталога (numpy)."""
    import numpy as np

    by_name = {name: idx for idx, name in class_names.items()}
    out: list[StructureResult] = []
    for key in keys:
        members = TS_GROUPS.get(key, (key,))
        ids = [by_name[m] for m in members if m in by_name]
        if not ids:
            continue
        mask = np.isin(labelmap, ids)
        count = int(mask.sum())
        if count == 0:
            continue  # структура не попала в поле обзора — находки нет
        nz = np.nonzero(mask)
        extent = tuple(int(ax.max() - ax.min() + 1) for ax in nz)
        out.append(StructureResult(key=key, voxel_count=count, extent_voxels=extent))
    return out


def weights_fingerprint(directory) -> str:
    """SHA-256 по всем файлам каталога весов (путь + содержимое) — для трассировки SR-5."""
    import hashlib
    from pathlib import Path

    root = Path(directory)
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(root)).encode())
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


# Наборы весов TotalSegmentator по задачам (открытые, Apache-2.0): быстрый режим 3 мм и полный.
TS_TASKS: dict[str, dict] = {
    "total": {"fast": (297,), "full": (291, 292, 293, 294, 295), "modality": "CT"},
    "total_mr": {"fast": (852,), "full": (850, 851), "modality": "MR"},
}


def ts_weight_dirs(weights_dir, task: str, fast: bool) -> list:
    """Каталоги весов задачи в кэше TotalSegmentator (по номеру набора Dataset<id>_)."""
    from pathlib import Path

    ids = TS_TASKS[task]["fast" if fast else "full"]
    root = Path(weights_dir)
    found = []
    for i in ids:
        match = sorted(d for d in root.glob(f"Dataset{i}_*") if d.is_dir())
        if not match:
            return []
        found.append(match[0])
    return found


def ts_fingerprint(weights_dir, task: str, fast: bool) -> str | None:
    dirs = ts_weight_dirs(weights_dir, task, fast)
    return "+".join(weights_fingerprint(d) for d in dirs) if dirs else None


class TotalSegmentatorAdapter(SegmentationModel):  # pragma: no cover - нужен TotalSegmentator
    """TotalSegmentator (Apache-2.0, задача total): органы КТ → маска и объёмы.

    fetch_series(prefix) -> list[bytes] — все DICOM-срезы серии (обезличенные, из S3);
    store_mask(key, bytes) -> ref — куда сохранить мультиметочную маску (NIfTI).
    Отпечаток каталога весов сверяется с зарегистрированным weights_hash (SR-5).
    """

    def __init__(self, weights_hash: str, keys: list[str], fetch_series, store_mask=None,
                 fast: bool = True, device: str = "cpu", task: str = "total") -> None:
        from totalsegmentator.config import get_weights_dir

        if task not in TS_TASKS:
            raise RuntimeError(f"Неизвестная задача TotalSegmentator: {task}")
        self.name = f"totalsegmentator_{task}"
        self.semver = "2"
        self.weights_hash = weights_hash
        self._keys, self._fetch, self._store = keys, fetch_series, store_mask
        self._fast, self._device, self._task = fast, device, task
        self.timeout_s = 1800
        actual = ts_fingerprint(get_weights_dir(), task, fast)
        if actual is None:
            raise FileNotFoundError(f"Нет весов TotalSegmentator ({task}) — запустите make totalseg-candidate")
        if actual != weights_hash:
            raise RuntimeError(f"Отпечаток весов TotalSegmentator не совпадает: {actual} != {weights_hash}")

    def infer(self, series_object_prefix: str, spacing: tuple[float, float, float]) -> SegmentationOutput:
        import gzip
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        import nibabel as nib
        import numpy as np
        from totalsegmentator.map_to_binary import class_map

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "dicom"
            src.mkdir()
            for i, data in enumerate(self._fetch(series_object_prefix)):
                (src / f"{i:05d}.dcm").write_bytes(data)
            out_file = Path(tmp) / "seg.nii.gz"
            cmd = [sys.executable, "-m", "app.workers.totalseg_runner", str(src), str(out_file),
                   "--device", self._device, "--task", self._task] + ([] if self._fast else ["--full"])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_s)
            if proc.returncode != 0 or not out_file.exists():
                raise RuntimeError(f"TotalSegmentator завершился с ошибкой: {proc.stderr[-500:]}")
            img = nib.load(str(out_file))
            img = nib.Nifti1Image(np.asarray(img.dataobj), img.affine, img.header)  # в память до удаления tmp
        labelmap = np.asarray(img.dataobj)
        zooms = tuple(float(z) for z in img.header.get_zooms()[:3])
        structures = labelmap_structures(labelmap, class_map[self._task], self._keys)
        ref = None
        if self._store is not None:
            key = f"{series_object_prefix}/totalseg_{self._task}_{self.weights_hash[:12]}.nii.gz"
            ref = self._store(key, gzip.compress(img.to_bytes()))
        return SegmentationOutput(
            mask_artifact_ref=ref,
            structures=structures,
            preprocessing_params={"adapter": "totalsegmentator", "task": self._task, "fast": self._fast,
                                  "mask_spacing_mm": list(zooms)},
            spacing_mm=zooms,
        )


class StubSegmentationModel(SegmentationModel):
    """Детерминированная заглушка без GPU и без пиксельных данных.

    Возвращает фиксированный набор структур с воспроизводимой воксельной
    статистикой, выведенной из префикса серии. Служит для сборки контура,
    сквозных тестов пайплайна и режима RESEARCH до интеграции реальной модели.
    """

    def __init__(self, structure_keys: list[str], weights_hash: str = "stub-0") -> None:
        self.name = "stub_segmentation"
        self.semver = "0.0.0"
        self.weights_hash = weights_hash
        self._keys = structure_keys

    def infer(self, series_object_prefix: str, spacing: tuple[float, float, float]) -> SegmentationOutput:
        import hashlib

        seed = int(hashlib.sha256(series_object_prefix.encode()).hexdigest()[:8], 16)
        structures: list[StructureResult] = []
        for i, key in enumerate(self._keys):
            # Детерминированный «объём»: одинаковый вход → одинаковый результат.
            voxel_count = 10_000 + (seed % 5000) + i * 1000
            structures.append(
                StructureResult(
                    key=key,
                    voxel_count=voxel_count,
                    extent_voxels=(50 + i, 60 + i, 40 + i),
                    density_values=[],
                )
            )
        return SegmentationOutput(
            mask_artifact_ref=f"{series_object_prefix}/mask_stub.nii.gz",
            structures=structures,
            preprocessing_params={"resample_mm": list(spacing), "adapter": "stub"},
        )
