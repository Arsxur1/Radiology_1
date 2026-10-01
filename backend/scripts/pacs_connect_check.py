"""Проверка подключения PACS клиники — по шагам, с подсказкой «что сделать» (FR-1).

    docker compose exec backend python scripts/pacs_connect_check.py            # шаги 1–5
    docker compose exec backend python scripts/pacs_connect_check.py --wait 15  # + ждать тестовое
        исследование от PACS до 15 мин и проверить, что оно пришло обезличенным

Данные пациентов не выводятся: только числа и «да/нет». Код выхода 0 — всё в порядке.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ICON = {True: "✓", False: "✗", None: "–"}


def wait_for_study(minutes: float):
    """Шаг 6: ждать новое исследование и проверить обезличивание в clean-Orthanc."""
    from sqlalchemy import func, select

    from app.db.session import SessionLocal
    from app.models.imaging import Study
    from app.services.orthanc import clean_client, raw_client
    from app.services.pacs_diagnose import Step

    db = SessionLocal()
    start = datetime.utcnow() - timedelta(seconds=5)
    before = db.execute(select(func.count()).select_from(Study)).scalar_one()
    print(f"  Ждём исследование от PACS (до {minutes:g} мин). Отправьте 1 тестовое исследование "
          "из PACS на узел платформы…", flush=True)
    deadline = time.monotonic() + minutes * 60
    study = None
    while time.monotonic() < deadline:
        study = db.execute(select(Study).where(Study.created_at >= start)
                           .order_by(Study.created_at.desc())).scalars().first()
        if study:
            break
        time.sleep(5)
        db.expire_all()
    if study is None:
        after = db.execute(select(func.count()).select_from(Study)).scalar_one()
        return Step("Приём от PACS", False, f"за {minutes:g} мин новых исследований нет (было {before}, стало {after})",
                    "Проверить в PACS узел платформы (IP:4242, AE MEDVIZ_RAW) и отправку; журналы: "
                    "docker compose logs orthanc-raw orthanc-watcher worker.")
    time.sleep(10)  # остальные срезы и удаление исходника из raw
    clean, raw = clean_client(), raw_client()
    iid = clean.find_study_instance(study.study_instance_uid)
    tags = clean.get_instance_tags(iid) if iid else {}
    anon = str(tags.get("PatientName", "")).startswith("ANON^") and tags.get("PatientIdentityRemoved") == "YES"
    raw_left = raw.instance_count()
    detail = (f"принято: модальность {study.modality}, аппарат указан: {'да' if study.manufacturer else 'нет'}, "
              f"возраст указан: {'да' if study.patient_age_years is not None else 'нет'}, "
              f"область (BodyPartExamined): {'да' if study.body_part else 'нет'}; "
              f"обезличено: {'да' if anon else 'НЕТ'}; "
              f"в orthanc-raw осталось снимков: {raw_left}")
    ok = anon
    remedy = "" if ok else "Обезличенная копия не найдена или содержит ФИО — остановить приём и сообщить разработчикам."
    if ok and (study.patient_age_years is None or not study.body_part):
        remedy = "Без возраста/области модели будут отказывать (SR-7): см. «Готовность данных площадки»."
    return Step("Приём от PACS", ok, detail, remedy)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--receiver", default="orthanc-raw:4242", help="наш приёмник DICOM host:port")
    p.add_argument("--receiver-aet", default=None, help="AE приёмника (по умолчанию PACS_LOCAL_AET)")
    p.add_argument("--find-date", default=(date.today() - timedelta(days=1)).strftime("%Y%m%d"))
    p.add_argument("--wait", type=float, default=0, help="минут ждать тестовое исследование от PACS")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    from app.core.config import get_settings
    from app.services import pacs_diagnose as d
    from app.services.pacs import default_node_from_settings

    s = get_settings()
    node = default_node_from_settings()
    steps = [d.check_settings(node)]
    if node:
        steps.append(tcp := d.check_tcp(node))
        if tcp.ok:
            steps.append(echo := d.check_echo(node))
            if echo.ok:
                steps.append(d.check_find(node, a.find_date))
    host, _, port = a.receiver.rpartition(":")
    steps.append(d.check_receiver(host, int(port), a.receiver_aet or s.pacs_local_aet))
    if a.wait:
        steps.append(wait_for_study(a.wait))

    if a.json:
        print(json.dumps(d.as_dicts(steps), ensure_ascii=False, indent=2))
    else:
        for st in steps:
            print(f"{ICON[st.ok]} {st.name}: {st.detail}")
            if st.remedy and st.ok is not True:
                print(f"    → {st.remedy}")
            elif st.remedy:
                print(f"    ! {st.remedy}")
    sys.exit(0 if all(st.ok is not False for st in steps) else 1)


if __name__ == "__main__":
    main()
