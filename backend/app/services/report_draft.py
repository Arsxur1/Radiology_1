"""Черновик заключения из подтверждённых находок (ТЗ, FR-8).

Инварианты (нарушение любого делает систему непригодной к клинике, раздел 11):
- Черновик формируется ТОЛЬКО из подтверждённых структурированных находок.
  Неподтверждённая находка в наборе → отказ.
- Языковая модель (или детерминированный шаблон) лишь превращает готовые числа
  и коды в связный текст. Она НЕ анализирует изображения, не формирует находки и
  не добавляет утверждений, отсутствующих в структурированных данных.
- Каждое предложение трассируется до конкретной записи finding (sentence_map).
- Обратное направление (разбор текста на находки) не поддерживается — такой
  операции в модуле нет.

Рендерер по умолчанию — детерминированный шаблон (работает офлайн, воспроизводим).
Локальная LLM может заменить рендерер, получая на вход те же структурированные
данные и не имея доступа к изображениям (см. VOPROSY-K-TZ.md, п. 32).
"""

from __future__ import annotations

from dataclasses import dataclass, field


class UnconfirmedFindingError(Exception):
    """Попытка включить в черновик неподтверждённую находку (нарушение FR-8)."""


@dataclass
class FindingInput:
    finding_id: str
    label: str | None
    code: str | None
    coding_system: str
    measurements: dict
    confirmed: bool


@dataclass
class DraftSentence:
    text: str
    finding_id: str        # трассировка до конкретной находки (FR-8)


@dataclass
class ReportDraft:
    language: str
    sentences: list[DraftSentence] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)

    @property
    def sentence_map(self) -> dict:
        # индекс предложения → finding_id (для приёмки: трассируемость)
        return {str(i): s.finding_id for i, s in enumerate(self.sentences)}


# Единицы измерения и подписи метрик по языкам.
_METRIC_LABELS = {
    "ru": {"volume_ml": "объём", "unit_volume": "мл"},
    "uz": {"volume_ml": "hajm", "unit_volume": "ml"},
    "en": {"volume_ml": "volume", "unit_volume": "ml"},
}


def _render_sentence(f: FindingInput, language: str) -> str:
    """Детерминированный шаблон: структура + числа. Никаких добавленных смыслов."""
    labels = _METRIC_LABELS.get(language, _METRIC_LABELS["ru"])
    name = f.label or f.code or "структура"
    parts: list[str] = []
    vol = f.measurements.get("volume_ml")
    if isinstance(vol, (int, float)):
        parts.append(f"{labels['volume_ml']} {vol} {labels['unit_volume']}")
    linear = f.measurements.get("linear_size_mm")
    if isinstance(linear, dict):
        dims = ", ".join(f"{k}: {v} мм" for k, v in linear.items())
        parts.append(f"размеры ({dims})")
    code_ref = f" [{f.coding_system}:{f.code}]" if f.code else ""
    if parts:
        return f"{name}{code_ref} — {'; '.join(parts)}."
    return f"{name}{code_ref} — измерения отсутствуют."


def build_draft(findings: list[FindingInput], *, language: str = "ru") -> ReportDraft:
    """Собрать черновик из подтверждённых находок. Отказ при неподтверждённых (FR-8)."""
    unconfirmed = [f.finding_id for f in findings if not f.confirmed]
    if unconfirmed:
        raise UnconfirmedFindingError(
            "Черновик собирается только из подтверждённых находок. "
            f"Неподтверждённые: {unconfirmed}"
        )

    # Детерминированный порядок: по коду, затем по id.
    ordered = sorted(findings, key=lambda f: (f.code or "", f.finding_id))
    draft = ReportDraft(language=language)
    for f in ordered:
        draft.sentences.append(DraftSentence(text=_render_sentence(f, language), finding_id=f.finding_id))
    return draft
