"""Гейт границ применимости (ТЗ, SR-7).

Если серия не соответствует валидированному диапазону модели (толщина среза,
возраст, модальность, наличие контраста, производитель аппарата), система
возвращает ЯВНЫЙ ОТКАЗ с указанием причины. Выдача результата «с пониженной
уверенностью» вне диапазона запрещена — поэтому здесь только бинарное решение
допустить/отказать со списком причин.

Границы применимости хранятся в model_version.applicability (JSONB). Пример:
{
  "modality": ["CT"],
  "body_part": ["CHEST", "THORAX"],
  "slice_thickness_mm": {"max": 3.0},
  "age": {"min_years": 18},          # только взрослые (педиатрия — раздельно, п.1.2)
  "manufacturers": ["Siemens", "GE", "Philips", "Canon"],
  "allow_lossy": false,
  "require_contrast": null            # null = не важно
}
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SeriesContext:
    """Обезличенные признаки серии для проверки применимости."""

    modality: str | None
    body_part: str | None
    slice_thickness_mm: float | None
    manufacturer: str | None
    lossy_compressed: bool
    contrast_agent: bool | None
    patient_age_years: float | None


@dataclass
class ApplicabilityDecision:
    admitted: bool
    reasons: list[str] = field(default_factory=list)  # почему отказано


def _norm(value: str | None) -> str:
    return (value or "").strip().upper()


def check_applicability(
    ctx: SeriesContext, applicability: dict
) -> ApplicabilityDecision:
    """Проверить серию против границ применимости модели (SR-7).

    Возвращает отказ со всеми нарушенными условиями. Отсутствующее в серии
    обязательное для проверки поле трактуется в пользу отказа (раздел 11:
    неоднозначность — в сторону более явного участия/осторожности).
    """
    reasons: list[str] = []

    allowed_modalities = [_norm(m) for m in applicability.get("modality", [])]
    if allowed_modalities and _norm(ctx.modality) not in allowed_modalities:
        reasons.append(
            f"Модальность {ctx.modality!r} вне диапазона {applicability.get('modality')}"
        )

    allowed_parts = [_norm(p) for p in applicability.get("body_part", [])]
    if allowed_parts:
        if ctx.body_part is None:
            reasons.append("Не указана область исследования (body_part), требуется проверка")
        elif _norm(ctx.body_part) not in allowed_parts:
            reasons.append(
                f"Область {ctx.body_part!r} вне диапазона {applicability.get('body_part')}"
            )

    st = applicability.get("slice_thickness_mm", {})
    if st:
        if ctx.slice_thickness_mm is None:
            reasons.append("Не указана толщина среза — модель требует её для проверки")
        else:
            if "max" in st and ctx.slice_thickness_mm > st["max"]:
                reasons.append(
                    f"Толщина среза {ctx.slice_thickness_mm} мм > максимума {st['max']} мм"
                )
            if "min" in st and ctx.slice_thickness_mm < st["min"]:
                reasons.append(
                    f"Толщина среза {ctx.slice_thickness_mm} мм < минимума {st['min']} мм"
                )

    age = applicability.get("age", {})
    if age:
        if ctx.patient_age_years is None:
            reasons.append("Не указан возраст — границы применимости требуют его (взрослые/дети)")
        else:
            if "min_years" in age and ctx.patient_age_years < age["min_years"]:
                reasons.append(
                    f"Возраст {ctx.patient_age_years} < минимума {age['min_years']} "
                    "(модель валидирована только для взрослых, педиатрия — раздельно)"
                )
            if "max_years" in age and ctx.patient_age_years > age["max_years"]:
                reasons.append(f"Возраст {ctx.patient_age_years} > максимума {age['max_years']}")

    allowed_manuf = [_norm(m) for m in applicability.get("manufacturers", [])]
    if allowed_manuf and _norm(ctx.manufacturer) not in allowed_manuf:
        reasons.append(
            f"Аппарат {ctx.manufacturer!r} вне валидированного списка "
            f"{applicability.get('manufacturers')}"
        )

    if not applicability.get("allow_lossy", False) and ctx.lossy_compressed:
        reasons.append("Серия сжата с потерями, а модель этого не допускает")

    require_contrast = applicability.get("require_contrast", None)
    if require_contrast is not None and ctx.contrast_agent is not None:
        if require_contrast and not ctx.contrast_agent:
            reasons.append("Модель требует контраст, а в серии его нет")
        if not require_contrast and ctx.contrast_agent:
            reasons.append("Модель валидирована без контраста, а серия контрастная")

    return ApplicabilityDecision(admitted=not reasons, reasons=reasons)
