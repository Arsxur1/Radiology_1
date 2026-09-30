"""Движок совмещения на SimpleITK (FR-4): жёсткая → аффинная → деформируемая (B-сплайн).

Метрика — Mattes mutual information (подходит для разных модальностей: КТ↔МРТ).
Каждая стадия стартует с результата предыдущей. Количественная оценка качества:
  - MI до совмещения (только выравнивание центров) и после каждой стадии;
  - Dice «тело пациента» (порог Оцу) до и после — грубая, но наглядная проверка;
  - для деформируемой стадии — минимум якобиана поля смещений: ≤ 0 означает
    «складку» (физически невозможную деформацию) — такой результат врачу не подтвердить.
Для визуальной проверки врачом строится превью-«шахматка» (фиксированная | совмещённая)
по трём центральным срезам.

Детерминированность (FR-6): фиксированное зерно выборки метрики и расчёт в один поток
(проверено повторными запусками; при нескольких потоках результат плавает).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.models.registration import RegistrationStage
from app.services.registration import STAGE_ORDER, RegistrationEngine, RegistrationOutput

SEED = 20260930
WORK_SPACING_MM = 2.0      # рабочая сетка: не мельче 2 мм и не мельче исходных вокселей
# Один поток: уже при двух результат аффинной стадии плавает между запусками
# (проверено повторными прогонами), а воспроизводимость обязательна (FR-6).
THREADS = 1
BSPLINE_MESH_MM = 50.0     # шаг сетки контрольных точек B-сплайна
BSPLINE_ITERATIONS = 100   # лимит итераций L-BFGS-B на уровень пирамиды


def _mattes(reg, bins: int = 50) -> None:
    import SimpleITK as sitk

    reg.SetMetricAsMattesMutualInformation(numberOfHistogramBins=bins)
    reg.SetMetricSamplingStrategy(reg.RANDOM)
    reg.SetMetricSamplingPercentage(0.15, SEED)
    reg.SetInterpolator(sitk.sitkLinear)


def resample_iso(image, spacing: float = WORK_SPACING_MM):
    import SimpleITK as sitk

    old_sp, old_size = image.GetSpacing(), image.GetSize()
    size = [max(1, int(round(sz * sp / spacing))) for sz, sp in zip(old_size, old_sp, strict=True)]
    return sitk.Resample(image, size, sitk.Transform(), sitk.sitkLinear, image.GetOrigin(),
                         (spacing,) * 3, image.GetDirection(), float(_min_value(image)), sitk.sitkFloat32)


def _min_value(image) -> float:
    import SimpleITK as sitk

    f = sitk.MinimumMaximumImageFilter()
    f.Execute(image)
    return f.GetMinimum()


def mutual_information(fixed, moving, transform) -> float:
    """MI (больше — лучше). SimpleITK возвращает Mattes MI со знаком минус."""
    import SimpleITK as sitk

    reg = sitk.ImageRegistrationMethod()
    _mattes(reg)
    reg.SetInitialTransform(transform)
    return round(-reg.MetricEvaluate(fixed, moving), 4)


def body_mask(image):
    import SimpleITK as sitk

    m = sitk.OtsuThreshold(image, 0, 1)
    return sitk.BinaryMorphologicalOpening(m, [2, 2, 2])


def dice(fixed, moving, transform) -> float:
    import SimpleITK as sitk

    fm = body_mask(fixed)
    mm = sitk.Resample(body_mask(moving), fixed, transform, sitk.sitkNearestNeighbor, 0, fm.GetPixelID())
    f = sitk.LabelOverlapMeasuresImageFilter()
    f.Execute(fm, mm)
    return round(f.GetDiceCoefficient(), 4)


def _run(reg, fixed, moving):
    reg.SetShrinkFactorsPerLevel([4, 2, 1])
    reg.SetSmoothingSigmasPerLevel([2, 1, 0])
    reg.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    return reg.Execute(fixed, moving)


def register_images(fixed, moving, up_to_stage: RegistrationStage) -> tuple:
    """Совместить два 3D-изображения. Возвращает (итоговое преобразование, качество)."""
    import SimpleITK as sitk

    sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(THREADS)
    started = time.monotonic()
    # Не увеличиваем сетку сверх исходного разрешения: это только замедляет расчёт.
    spacing = max(WORK_SPACING_MM, min(min(fixed.GetSpacing()), min(moving.GetSpacing())))
    fixed = resample_iso(sitk.Cast(fixed, sitk.sitkFloat32), spacing)
    moving = resample_iso(sitk.Cast(moving, sitk.sitkFloat32), spacing)
    stages = STAGE_ORDER[: STAGE_ORDER.index(up_to_stage) + 1]

    init = sitk.CenteredTransformInitializer(fixed, moving, sitk.Euler3DTransform(),
                                             sitk.CenteredTransformInitializerFilter.GEOMETRY)
    quality: dict = {"engine": "simpleitk", "engine_version": sitk.Version_VersionString(),
                     "work_spacing_mm": round(spacing, 2),
                     "mi_initial": mutual_information(fixed, moving, init),
                     "dice_initial": dice(fixed, moving, init), "stages": {}}

    # 1. Жёсткая: поворот + сдвиг.
    reg = sitk.ImageRegistrationMethod()
    _mattes(reg)
    reg.SetOptimizerAsRegularStepGradientDescent(learningRate=2.0, minStep=1e-4, numberOfIterations=200,
                                                 relaxationFactor=0.5)
    reg.SetOptimizerScalesFromPhysicalShift()
    reg.SetInitialTransform(sitk.Euler3DTransform(init), inPlace=False)
    rigid = _run(reg, fixed, moving)
    transform = rigid
    quality["stages"]["rigid"] = {"mi": mutual_information(fixed, moving, rigid),
                                  "dice": dice(fixed, moving, rigid)}

    # 2. Аффинная: + масштаб и сдвиг, стартует с жёсткой.
    if RegistrationStage.AFFINE in stages:
        euler = sitk.Euler3DTransform(sitk.CompositeTransform(rigid).GetNthTransform(0)) \
            if isinstance(rigid, sitk.CompositeTransform) else sitk.Euler3DTransform(rigid)
        affine = sitk.AffineTransform(3)
        affine.SetMatrix(euler.GetMatrix())
        affine.SetTranslation(euler.GetTranslation())
        affine.SetCenter(euler.GetCenter())
        # Быстрый градиентный спуск; если он ухудшил MI (бывает при сильном различии
        # контрастов) — повтор сопряжёнными градиентами с линейным поиском: медленнее, устойчивее.
        candidate = None
        for optimizer in ("rsgd", "cg"):
            reg = sitk.ImageRegistrationMethod()
            _mattes(reg)
            if optimizer == "rsgd":
                reg.SetOptimizerAsRegularStepGradientDescent(learningRate=0.5, minStep=1e-4,
                                                             numberOfIterations=200, relaxationFactor=0.5)
            else:
                reg.SetOptimizerAsConjugateGradientLineSearch(learningRate=1.0, numberOfIterations=100,
                                                              convergenceMinimumValue=1e-6,
                                                              convergenceWindowSize=10)
            reg.SetOptimizerScalesFromPhysicalShift()
            reg.SetInitialTransform(sitk.AffineTransform(affine), inPlace=False)
            candidate = _run(reg, fixed, moving)
            if mutual_information(fixed, moving, candidate) >= quality["stages"]["rigid"]["mi"] - 1e-3:
                break
        quality["affine_optimizer"] = optimizer
        transform = _accept_stage(quality, "affine", fixed, moving, candidate, transform)

    # 3. Деформируемая: B-сплайн поверх аффинной.
    if RegistrationStage.DEFORMABLE in stages:
        mesh = [max(1, int(round(sz * sp / BSPLINE_MESH_MM)))
                for sz, sp in zip(fixed.GetSize(), fixed.GetSpacing(), strict=True)]
        bspline = sitk.BSplineTransformInitializer(fixed, mesh)
        reg = sitk.ImageRegistrationMethod()
        _mattes(reg)
        reg.SetOptimizerAsLBFGSB(gradientConvergenceTolerance=1e-5, numberOfIterations=BSPLINE_ITERATIONS,
                                 maximumNumberOfCorrections=5,
                                 maximumNumberOfFunctionEvaluations=5 * BSPLINE_ITERATIONS)
        reg.SetMovingInitialTransform(transform)
        reg.SetInitialTransform(bspline, inPlace=True)
        reg.SetShrinkFactorsPerLevel([2, 1])
        reg.SetSmoothingSigmasPerLevel([1, 0])
        reg.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
        reg.Execute(fixed, moving)
        field = sitk.TransformToDisplacementField(bspline, sitk.sitkVectorFloat64, fixed.GetSize(),
                                                  fixed.GetOrigin(), fixed.GetSpacing(), fixed.GetDirection())
        jac = sitk.DisplacementFieldJacobianDeterminant(field)
        mm = sitk.MinimumMaximumImageFilter()
        mm.Execute(jac)
        transform = _accept_stage(quality, "deformable", fixed, moving,
                                  sitk.CompositeTransform([transform, bspline]), transform,
                                  jacobian_min=round(mm.GetMinimum(), 4), jacobian_max=round(mm.GetMaximum(), 4))

    achieved = [s for s in stages if quality["stages"].get(s.value, {}).get("accepted", True)]
    quality["achieved_stage"] = achieved[-1].value
    last = quality["stages"][achieved[-1].value]
    quality["mutual_information"] = last["mi"]
    quality["warnings"] = quality_warnings(quality)
    quality["runtime_s"] = round(time.monotonic() - started, 1)
    return transform, quality, fixed, moving


def _accept_stage(quality: dict, name: str, fixed, moving, candidate, previous, **extra):
    """Стадия принимается, только если не ухудшила MI относительно предыдущей.

    Иначе результат предыдущей стадии сохраняется, а отказ записывается в качество —
    врач видит, до какой стадии совмещение дошло на самом деле.
    """
    prev_mi = next(quality["stages"][s]["mi"] for s in ("affine", "rigid") if s in quality["stages"]
                   and quality["stages"][s].get("accepted", True))
    mi = mutual_information(fixed, moving, candidate)
    accepted = mi >= prev_mi - 1e-3
    quality["stages"][name] = {"mi": mi, "dice": dice(fixed, moving, candidate), "accepted": accepted, **extra}
    return candidate if accepted else previous


def quality_warnings(q: dict) -> list[dict]:
    """Предупреждения для врача. blocking=True — подтвердить такое совмещение нельзя."""
    out = []
    stages = q.get("stages", {})
    last = next((stages[s] for s in ("deformable", "affine", "rigid")
                 if s in stages and stages[s].get("accepted", True)), None)
    for s in ("affine", "deformable"):
        if s in stages and not stages[s].get("accepted", True):
            out.append({"code": f"{s}_reverted", "blocking": False,
                        "text": f"Стадия {s} ухудшила совмещение и не применена"})
    if last and last["mi"] < q["mi_initial"]:
        out.append({"code": "mi_decreased", "blocking": False,
                    "text": "Взаимная информация после совмещения ниже исходной — проверьте визуально"})
    if last and last["dice"] < q["dice_initial"] - 0.02:
        out.append({"code": "dice_decreased", "blocking": False,
                    "text": "Перекрытие контуров тела ухудшилось после совмещения"})
    if last and last["dice"] < 0.7:
        out.append({"code": "low_overlap", "blocking": False,
                    "text": f"Низкое перекрытие контуров тела (Dice {last['dice']})"})
    d = stages.get("deformable")
    if d and d.get("accepted", True) and d["jacobian_min"] <= 0:
        out.append({"code": "folding", "blocking": True,
                    "text": "Деформация со «складками» (якобиан ≤ 0) — физически невозможна"})
    return out


def checkerboard_png(fixed, moving, transform, squares: int = 8) -> bytes:
    """Превью для врача: шахматка «опорная | совмещённая» по трём центральным срезам."""
    import io

    import numpy as np
    import SimpleITK as sitk
    from PIL import Image

    resampled = sitk.Resample(moving, fixed, transform, sitk.sitkLinear, float(_min_value(moving)))

    def norm(img):
        a = sitk.GetArrayFromImage(img).astype(np.float32)  # (z, y, x)
        lo, hi = np.percentile(a, [1, 99])
        return np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)

    f, m = norm(fixed), norm(resampled)
    z, y, x = (s // 2 for s in f.shape)
    views = [(f[z], m[z]), (f[::-1, y, :], m[::-1, y, :]), (f[::-1, :, x], m[::-1, :, x])]
    tiles = []
    for a, b in views:
        h, w = a.shape
        yy, xx = np.mgrid[:h, :w]
        board = ((yy * squares // max(h, 1)) + (xx * squares // max(w, 1))) % 2 == 0
        tiles.append(np.where(board, a, b))
    height = max(t.shape[0] for t in tiles)
    padded = [np.pad(t, ((0, height - t.shape[0]), (0, 4))) for t in tiles]
    img = Image.fromarray((np.concatenate(padded, axis=1) * 255).astype(np.uint8))
    if img.height < 256:  # рабочая сетка 2 мм — увеличить для глаза врача
        k = 256 / img.height
        img = img.resize((int(img.width * k), 256), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def read_series(dicom_bytes: list[bytes]):  # pragma: no cover - нужен S3
    """Срезы DICOM (bytes) → 3D-изображение SimpleITK."""
    import tempfile
    from pathlib import Path

    import SimpleITK as sitk

    with tempfile.TemporaryDirectory() as tmp:
        for i, data in enumerate(dicom_bytes):
            (Path(tmp) / f"{i:05d}.dcm").write_bytes(data)
        reader = sitk.ImageSeriesReader()
        names = reader.GetGDCMSeriesFileNames(tmp)
        if len(names) < 3:
            raise ValueError("Для совмещения нужна объёмная серия (≥ 3 срезов)")
        reader.SetFileNames(names)
        return reader.Execute()


class ItkRegistrationEngine(RegistrationEngine):
    """load(prefix) -> sitk.Image; store(key, bytes, content_type) -> ref."""

    def __init__(self, load: Callable | None = None, store: Callable | None = None) -> None:
        if load is None:  # pragma: no cover - продуктивный путь
            from app.services import storage

            def load(prefix):
                return read_series(storage.series_objects(prefix))
        self._load, self._store = load, store

    def register(self, fixed_prefix: str, moving_prefix: str,
                 up_to_stage: RegistrationStage) -> RegistrationOutput:
        import SimpleITK as sitk

        transform, quality, fixed, moving = register_images(self._load(fixed_prefix), self._load(moving_prefix),
                                                            up_to_stage)
        transform_ref = preview_ref = None
        if self._store is not None:
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "transform.tfm"
                sitk.WriteTransform(transform, str(path))
                base = f"{moving_prefix}/registration/{fixed_prefix.replace('/', '_')}_{up_to_stage.value}"
                transform_ref = self._store(f"{base}.tfm", path.read_bytes(), "text/plain")
            preview_ref = self._store(f"{base}.png", checkerboard_png(fixed, moving, transform), "image/png")
        quality["preview_ref"] = preview_ref
        return RegistrationOutput(stage=RegistrationStage(quality["achieved_stage"]),
                                  metric_value=quality["mutual_information"],
                                  quality=quality, transform_ref=transform_ref)
