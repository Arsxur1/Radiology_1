"""Готовность данных площадки: что на самом деле присылают аппараты клиники (пилот, SR-7).

Модели отказывают (SR-7), если в DICOM нет области исследования или возраста, а
кириллица без указанной кодировки искажает описания. Раньше это проверялось вручную на
выгрузке DICOM; теперь — сводкой по уже принятым исследованиям, по каждому аппарату.

Только агрегаты, без идентификаторов. Нераспознанные описания исследований (по ним
дописывается словарь областей) показываются, лишь если строка встречается не менее чем в
MIN_DESCRIPTION_COUNT исследованиях; цифры заменяются на «#», длина ограничена — в
описание иногда вписывают ФИО или номер, и редкая строка могла бы указать на человека.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imaging import Series, Study
from app.services.shadow_eval import AGE_GROUPS, age_group
from app.services.structure_catalog import region_for_study

MIN_DESCRIPTION_COUNT = 5
TOP_DESCRIPTIONS = 30
# Доля исследований аппарата с признаком, ниже которой — замечание.
WARN_BELOW = 0.95


def _mask(text: str) -> str:
    return re.sub(r"\d", "#", " ".join(text.split()))[:64]


def _pct(n: int, total: int) -> float | None:
    return round(n / total, 4) if total else None


def build_site_data_report(db: Session, *, days: int = 90, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=days)).replace(tzinfo=None)
    rows = db.execute(
        select(Study.id, Study.modality, Study.manufacturer, Study.manufacturer_model, Study.body_part,
               Study.protocol, Study.description, Study.patient_age_years, Study.charset_guessed)
        .where(Study.created_at >= since)
    ).all()
    # Исследования, где возможен текст с данными пациента в пикселях (BurnedInAnnotation / вторичная копия).
    burned = set(db.execute(
        select(Series.study_id).join(Study, Series.study_id == Study.id)
        .where(Study.created_at >= since, Series.burned_in_risk.is_(True))
    ).scalars())

    devices: dict[str, Counter] = defaultdict(Counter)
    modalities: Counter = Counter()
    region_source: Counter = Counter()
    ages: Counter = Counter()
    charsets: Counter = Counter()
    unknown_desc: Counter = Counter()
    for study_id, modality, manuf, model, body_part, protocol, description, age, charset in rows:
        key = " · ".join(x for x in ((manuf or "").strip() or "аппарат не указан", (model or "").strip()) if x)
        d = devices[key]
        d["studies"] += 1
        d[f"modality:{modality}"] += 1
        if study_id in burned:
            d["burned_in_risk"] += 1
        modalities[modality] += 1
        if body_part:
            d["body_part"] += 1
        if age is not None:
            d["age"] += 1
        ages[age_group(age)] += 1
        if charset:
            d["charset_guessed"] += 1
            charsets[charset] += 1
        region = region_for_study(body_part, protocol, description)
        if region:
            d["region"] += 1
            region_source["body_part" if region_for_study(body_part, None, None) else "описание"] += 1
        else:
            region_source["не распознано"] += 1
            text = " / ".join(x for x in (protocol, description) if x)
            unknown_desc[_mask(text) if text else "(пусто)"] += 1

    per_device = []
    issues = []
    for key, d in sorted(devices.items(), key=lambda kv: -kv[1]["studies"]):
        n = d["studies"]
        item = {
            "device": key,
            "studies": n,
            "modalities": sorted(m.split(":", 1)[1] for m in d if m.startswith("modality:")),
            "body_part_share": _pct(d["body_part"], n),
            "age_share": _pct(d["age"], n),
            "region_share": _pct(d["region"], n),
            "charset_guessed": d["charset_guessed"],
            "burned_in_risk": d["burned_in_risk"],
        }
        per_device.append(item)
        if item["age_share"] < WARN_BELOW:
            issues.append(f"{key}: возраст (PatientAge) есть лишь в {item['age_share']:.0%} исследований — "
                          "без возраста модели отказывают, серии не идут в обучение. Включить в настройках "
                          "аппарата/PACS передачу PatientAge.")
        if item["body_part_share"] < WARN_BELOW:
            # Конечности и прочее законно не распознаются (моделей для них нет), поэтому
            # замечание — об отсутствии тега, а нераспознанное проверяет человек по списку.
            head = f"{key}: BodyPartExamined передаётся лишь в {item['body_part_share']:.0%} исследований"
            if item["region_share"] >= 1:
                issues.append(f"{head}; область пока удаётся определить по описанию. Надёжнее включить "
                              "передачу тега на аппарате.")
            else:
                issues.append(f"{head}; по описанию область не определена в {1 - item['region_share']:.0%}. "
                              "Проверьте список нераспознанных описаний: если там есть грудная клетка, "
                              "живот или голова — сообщите нам; лучше включить передачу тега на аппарате.")
        if d["burned_in_risk"]:
            issues.append(f"{key}: в {d['burned_in_risk']} исследованиях возможен текст с данными пациента в самом "
                          "изображении (BurnedInAnnotation или копия экрана) — в обучение они не идут; проверить, "
                          "не впечатывает ли аппарат ФИО в снимок, и выключить это в настройках.")
        if d["charset_guessed"]:
            issues.append(f"{key}: в {d['charset_guessed']} исследованиях кодировка текста не указана "
                          "(угадана при приёме) — настроить SpecificCharacterSet = ISO_IR 192 на аппарате.")

    total = len(rows)
    return {
        "days": days,
        "studies": total,
        "modalities": dict(modalities.most_common()),
        "age_groups": {g: ages[g] for _, _, g in (*AGE_GROUPS, (0, 0, "возраст неизвестен")) if ages[g]},
        "region_source": dict(region_source),
        "charset_guessed": dict(charsets),
        "per_device": per_device,
        "unrecognized_descriptions": [
            {"text": t, "studies": c} for t, c in unknown_desc.most_common()
            if c >= MIN_DESCRIPTION_COUNT][:TOP_DESCRIPTIONS],
        "rare_unrecognized_studies": sum(c for c in unknown_desc.values() if c < MIN_DESCRIPTION_COUNT),
        "min_description_count": MIN_DESCRIPTION_COUNT,
        "issues": issues,
        "ready": total > 0 and not issues,
    }
