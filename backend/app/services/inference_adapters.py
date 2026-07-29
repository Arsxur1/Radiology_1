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


class SegmentationModel(ABC):
    """Контракт модели сегментации."""

    name: str
    semver: str
    weights_hash: str

    @abstractmethod
    def infer(self, series_object_prefix: str, spacing: tuple[float, float, float]) -> SegmentationOutput:
        """Выполнить сегментацию серии. Детерминированно при фиксированных весах."""
        raise NotImplementedError


class TotalSegmentatorAdapter(SegmentationModel):
    """Адаптер TotalSegmentator (подключается на GPU-стенде).

    Реализация загружает серию из объектного хранилища, прогоняет модель и
    отдаёт маски + воксельную статистику. Здесь только контур; тело inference
    заполняется при интеграции (см. VOPROSY-K-TZ.md, п. 34 о лицензиях весов).
    """

    def __init__(self, weights_hash: str, semver: str = "0.0.0") -> None:
        self.name = "totalsegmentator_chest"
        self.semver = semver
        self.weights_hash = weights_hash

    def infer(  # pragma: no cover
        self, series_object_prefix: str, spacing: tuple[float, float, float]
    ) -> SegmentationOutput:
        # Ленивая загрузка тяжёлых зависимостей — только на стенде.
        # from totalsegmentator.python_api import totalsegmentator
        raise NotImplementedError(
            "TotalSegmentator подключается на стенде с GPU; см. docs/STAGE-2.md"
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
