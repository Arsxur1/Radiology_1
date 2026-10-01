"""Нагрузочные данные: «год работы детской клиники» в ОТДЕЛЬНОЙ базе — для замеров.

    POSTGRES_DB=medviz_load python scripts/load_seed.py --studies 60000

Только синтетика (никаких реальных данных). Создаёт пациентов, исследования (в основном
рентген ОГК детей), прогоны действующей и двух теневых моделей, находки, решения врачей,
подписанные заключения, отказы ИИ и журнал аудита с корректной хеш-цепочкой.
Отказывается работать с базой без «load» в имени — чтобы не засорить рабочую.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.audit import AuditAction, AuditLog
from app.models.imaging import Series, Study
from app.models.ml import (
    AiRefusal,
    ConfirmationStatus,
    Correction,
    CorrectionType,
    Finding,
    FindingSource,
    InferenceResult,
    ModelStatus,
    ModelVersion,
    Report,
)
from app.models.patient import Patient

CODES = ["CXR-104", "CXR-200", "CXR-201", "CXR-300", "CXR-500"]
OPS = {c: {"threshold": 0.5} for c in ["CXR-000", *CODES]}
PEDS = {"modality": ["CR", "DX"], "body_part": ["CHEST", "THORAX"], "age": {"min_years": 0, "max_years": 18},
        "allow_lossy": False}
DEVICES = ["Philips", "Siemens", "Shimadzu"]
DOCTORS = [f"dr.{i}" for i in range(12)]


def chunks(rows: list, n: int = 5000):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def bulk(db, model, rows: list) -> None:
    for part in chunks(rows):
        db.execute(insert(model.__table__), part)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--studies", type=int, default=60000)
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()
    if "load" not in get_settings().postgres_db:
        raise SystemExit("Только для отдельной базы с «load» в имени (POSTGRES_DB=medviz_load)")
    rnd = random.Random(a.seed)
    t0 = time.monotonic()
    start = datetime.now(UTC) - timedelta(days=365)
    db = SessionLocal()

    models = {
        "active": dict(id=uuid.uuid4(), name="cxr_peds", semver="1.0.0", status=ModelStatus.ACTIVE),
        "shadow1": dict(id=uuid.uuid4(), name="cxr_peds", semver="1.1.0", status=ModelStatus.SHADOW),
        "shadow2": dict(id=uuid.uuid4(), name="xrv_all", semver="0.3.0", status=ModelStatus.SHADOW),
    }
    bulk(db, ModelVersion, [dict(m, weights_hash="load-" + k, applicability=PEDS, task="classification",
                                 operating_points=OPS, adapter={}, evidence={}) for k, m in models.items()])

    patients, studies, series, infers, findings, reports, corrections, refusals = [], [], [], [], [], [], [], []
    n_pat = max(1, a.studies // 2)
    pat_ids = [uuid.uuid4() for _ in range(n_pat)]
    patients = [dict(id=pid) for pid in pat_ids]
    for _ in range(a.studies):
        when = start + timedelta(minutes=rnd.randrange(365 * 24 * 60))
        modality = rnd.choices(["DX", "CT", "MR"], [90, 7, 3])[0]
        sid, seid = uuid.uuid4(), uuid.uuid4()
        age = rnd.choice([rnd.uniform(0, 1), rnd.uniform(1, 5), rnd.uniform(5, 12), rnd.uniform(12, 18)])
        studies.append(dict(id=sid, patient_id=rnd.choice(pat_ids), study_instance_uid=f"2.25.{sid.int}",
                            modality=modality, study_date=when, manufacturer=rnd.choice(DEVICES),
                            protocol="Chest PA" if modality == "DX" else "Abdomen", patient_age_years=age,
                            created_at=when))
        series.append(dict(id=seid, study_id=sid, series_instance_uid=f"2.25.{seid.int}", modality=modality,
                           lossy_compressed=False, object_prefix=f"load/{seid}", created_at=when))
        finalized = rnd.random() < 0.85
        if finalized:
            reports.append(dict(id=uuid.uuid4(), study_id=sid, draft_text="Синтетика.", sentence_map={},
                                language="ru", finalized_by=rnd.choice(DOCTORS), created_at=when,
                                updated_at=when + timedelta(hours=2)))
        if modality != "DX":
            continue
        if rnd.random() < 0.04:                      # вне границ применимости — отказ ИИ
            refusals.append(dict(id=uuid.uuid4(), series_id=seid, model_version_id=models["active"]["id"],
                                 reasons=["возраст вне диапазона"], created_at=when))
            continue
        for key, m in models.items():
            iid = uuid.uuid4()
            drafted = [c for c in CODES if rnd.random() < 0.12]
            infers.append(dict(id=iid, series_id=seid, model_version_id=m["id"], shadow_run=key != "active",
                               preprocessing_params={}, metrics={"drafted": drafted}, created_at=when))
            for code in drafted:
                fid = uuid.uuid4()
                status = ConfirmationStatus.PENDING
                if key == "active" and finalized:
                    status = rnd.choices([ConfirmationStatus.CONFIRMED, ConfirmationStatus.REJECTED], [7, 3])[0]
                findings.append(dict(id=fid, series_id=seid, inference_result_id=iid, coding_system="MEDVIZ-CXR",
                                     code=code, label=code, measurements={"confidence": 0.7},
                                     coordinates={}, source=FindingSource.MODEL, confirmation_status=status,
                                     created_at=when))
                if status != ConfirmationStatus.PENDING:
                    corrections.append(dict(
                        id=uuid.uuid4(), finding_id=fid, series_id=seid, author=rnd.choice(DOCTORS),
                        correction_type=CorrectionType.ACCEPTED if status == ConfirmationStatus.CONFIRMED
                        else CorrectionType.REJECTED, before={}, after={}, time_spent_seconds=12.0,
                        created_at=when + timedelta(minutes=30)))
        if finalized and rnd.random() < 0.15:          # находка, которую добавил врач
            findings.append(dict(id=uuid.uuid4(), series_id=seid, inference_result_id=None,
                                 coding_system="MEDVIZ-CXR", code=rnd.choice(CODES), label="врач",
                                 measurements={}, coordinates={}, source=FindingSource.PHYSICIAN,
                                 confirmation_status=ConfirmationStatus.CONFIRMED, created_at=when))
    for model, rows in ((Patient, patients), (Study, studies), (Series, series), (InferenceResult, infers),
                        (Finding, findings), (Correction, corrections), (Report, reports), (AiRefusal, refusals)):
        bulk(db, model, rows)
        print(f"{model.__tablename__}: {len(rows)}", flush=True)
    db.commit()

    # Журнал аудита: приём, открытия, решения, подписи — с корректной хеш-цепочкой.
    events = []
    for s in studies:
        events.append((s["created_at"], "pacs", AuditAction.STUDY_INGEST, "series", s["id"], {}))
        for _ in range(rnd.randint(1, 4)):
            events.append((s["created_at"] + timedelta(minutes=rnd.randint(5, 600)), rnd.choice(DOCTORS),
                           AuditAction.PATIENT_ACCESS, "study", s["id"], {"what": "открыто исследование"}))
    for c in corrections:
        events.append((c["created_at"], c["author"], AuditAction.CORRECTION, "finding", c["finding_id"], {}))
    for r in reports:
        events.append((r["updated_at"], r["finalized_by"], AuditAction.REPORT_FINALIZE, "report", r["id"], {}))
    events.sort(key=lambda e: e[0])
    prev, rows = None, []
    for seq, (ts, actor, action, etype, eid, details) in enumerate(events, start=1):
        payload = {"actor": actor, "actor_role": "radiologist", "action": action.value, "entity_type": etype,
                   "entity_id": str(eid), "details": details}
        h = hashlib.sha256(((prev or "") + json.dumps(payload, sort_keys=True, default=str)).encode()).hexdigest()
        rows.append(dict(id=uuid.uuid4(), created_at=ts, actor=actor, actor_role="radiologist", action=action,
                         entity_type=etype, entity_id=eid, details=details, seq=seq, prev_hash=prev, entry_hash=h))
        prev = h
    bulk(db, AuditLog, rows)
    db.commit()
    print(f"audit_log: {len(rows)}; всего {time.monotonic() - t0:.0f} с", flush=True)


if __name__ == "__main__":
    main()
