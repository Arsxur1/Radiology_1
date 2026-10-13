"""Сквозная проверка пути PACS на стенде разработки (НЕ для клиники): эмулятор H-PACS ↔ платформа.

    scripts/dev_stand.sh && scripts/dev_hpacs.sh        # стенд и эмулятор (PACS_* в .env стенда)
    cd backend && set -a && . ../.env && set +a && python3 scripts/dev_pacs_e2e.py

Шаги — как в клинике: в «H-PACS» два синтетических исследования одного «ребёнка» (имя
кириллицей, не данные пациентов) → H-PACS пересылает текущее платформе → оно обезличено →
врач находит прошлое в PACS без ФИО и загружает его (тот же псевдопациент) → врач подписывает
заключение → DICOM SR лёг к исходному исследованию в H-PACS, пациент и кириллица на месте.
Код выхода 0 — все шаги пройдены.
"""

from __future__ import annotations

import io
import os
import secrets
import sys
import time
from pathlib import Path

import httpx
import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API = os.environ.get("E2E_API", "http://localhost:8000")
HPACS = os.environ.get("E2E_HPACS_REST", "http://hpacs:8042")
DOCTOR = {"X-Debug-Subject": "e2e.doctor", "X-Debug-Roles": "radiologist"}
results: list[tuple[bool, str]] = []


def step(ok: bool, text: str) -> bool:
    results.append((ok, text))
    print(("✓ " if ok else "✗ ") + text, flush=True)
    return ok


def wait(fn, seconds: float = 60, every: float = 2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(every)
    return None


def make(mrn: str, date: str, desc: str, age: str, seed: int) -> tuple[str, bytes]:
    d = Dataset()
    d.file_meta = FileMetaDataset()
    d.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    d.file_meta.MediaStorageSOPClassUID = d.SOPClassUID = "1.2.840.10008.5.1.4.1.1.1"
    d.file_meta.MediaStorageSOPInstanceUID = d.SOPInstanceUID = generate_uid()
    d.StudyInstanceUID, d.SeriesInstanceUID = generate_uid(), generate_uid()
    d.SpecificCharacterSet = "ISO_IR 192"
    d.PatientID, d.PatientName, d.PatientBirthDate = mrn, "СИНТЕТИКОВ^ТЕСТ^РЕБЁНОК", "20190305"
    d.PatientAge, d.PatientSex = age, "M"
    d.InstitutionName, d.ReferringPhysicianName, d.AccessionNumber = "NCMC TEST", "ВРАЧЕВ^ВРАЧ", "ACC" + date
    d.Modality, d.BodyPartExamined, d.StudyDescription = "CR", "CHEST", desc
    d.StudyDate, d.StudyTime, d.SeriesNumber, d.InstanceNumber = date, "101500", 1, 1
    d.Rows = d.Columns = 128
    d.SamplesPerPixel, d.PhotometricInterpretation = 1, "MONOCHROME2"
    d.BitsAllocated = d.BitsStored = 16
    d.HighBit, d.PixelRepresentation = 15, 0
    d.PixelData = np.random.default_rng(seed).integers(0, 4000, (128, 128)).astype(np.uint16).tobytes()
    buf = io.BytesIO()
    d.save_as(buf, enforce_file_format=True)
    return d.StudyInstanceUID, buf.getvalue()


def main() -> int:
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.imaging import Study

    hp = httpx.Client(base_url=HPACS, timeout=60)
    api = httpx.Client(base_url=API, headers=DOCTOR, timeout=120)
    auth = (os.environ["ORTHANC_USERNAME"], os.environ["ORTHANC_PASSWORD"])
    mrn = "E2E-" + secrets.token_hex(4).upper()                 # новый синтетический «ребёнок»
    tag = mrn[-4:]

    # 1. Два исследования в H-PACS; пересылка текущего платформе.
    prior_uid, prior = make(mrn, "20250910", f"ОГК прямая, прошлое {tag}", "006Y", 1)
    cur_uid, cur = make(mrn, "20261013", f"ОГК прямая {tag}", "007Y", 2)
    hp.post("/instances", content=prior).raise_for_status()
    cur_orthanc = hp.post("/instances", content=cur).raise_for_status().json()["ParentStudy"]
    hp.post("/modalities/MEDVIZ_RAW/store", json=[cur_orthanc]).raise_for_status()

    def find(desc):
        with SessionLocal() as db:
            return db.execute(select(Study).where(Study.description == desc)).scalars().first()

    study = wait(lambda: find(f"ОГК прямая {tag}"))
    if not step(study is not None, "H-PACS → платформа: текущее исследование принято"):
        return 1
    clean = httpx.Client(base_url=os.environ.get("ORTHANC_CLEAN_URL", "http://orthanc-clean:8042"), auth=auth)
    found = clean.post("/tools/find", json={"Level": "Instance", "Query": {"StudyDescription": f"ОГК прямая {tag}"},
                                            "Expand": True}).json()
    tags = clean.get(f"/instances/{found[0]['ID']}/simplified-tags").json() if found else {}
    removed = all(k not in tags for k in ("PatientBirthDate", "InstitutionName", "ReferringPhysicianName",
                                          "AccessionNumber"))
    step(bool(tags) and tags.get("PatientID") != mrn and "СИНТЕТИКОВ" not in tags.get("PatientName", "")
         and removed and tags.get("StudyInstanceUID") != cur_uid,
         "обезличено: ФИО, номер карты, дата рождения, учреждение, врач, направление удалены, UID заменён")
    step(tags.get("PatientAge") == "007Y" and tags.get("BodyPartExamined") == "CHEST"
         and tags.get("StudyDescription") == f"ОГК прямая {tag}",
         "сохранены возраст, область и описание кириллицей")
    raw = httpx.get(os.environ.get("ORTHANC_RAW_URL", "http://orthanc-raw:8042") + "/statistics", auth=auth).json()
    step(raw["CountInstances"] == 0, "исходник с ФИО удалён из приёмника")

    # 2. Прошлые исследования в PACS — без ФИО; загрузка — тот же псевдопациент.
    priors = api.get(f"/studies/{study.id}/pacs-priors").raise_for_status().json()
    text = str(priors)
    past = [p for p in priors if not p["is_current"]]
    step(len(past) == 1 and past[0]["description"] == f"ОГК прямая, прошлое {tag}",
         "«Найти в PACS»: прошлое исследование с описанием кириллицей")
    step(mrn not in text and "СИНТЕТИКОВ" not in text and "20190305" not in text,
         "в ответе поиска нет ФИО, номера карты и даты рождения")
    api.post(f"/studies/{study.id}/pacs-priors/{past[0]['token']}/retrieve").raise_for_status()
    old = wait(lambda: find(f"ОГК прямая, прошлое {tag}"))
    step(old is not None and old.patient_id == study.patient_id and old.patient_age_years == 6,
         "«Загрузить»: прошлое принято и связано с тем же псевдопациентом (возраст на дату — 6)")

    # 3. Заключение: находка → черновик → подпись → в PACS.
    series_id = api.get(f"/studies/{study.id}").json()["series"][0]["id"]
    api.post("/findings", json={"series_id": series_id, "code": "CXR-200", "measurements": {},
                                "time_spent_seconds": 15}).raise_for_status()
    rep = api.post("/reports/generate", json={"study_id": str(study.id), "language": "ru"}).raise_for_status().json()
    api.post(f"/reports/{rep['id']}/finalize").raise_for_status()
    sent = api.post(f"/reports/{rep['id']}/send-to-pacs").raise_for_status().json()
    step(sent.get("sent") is True, "подписанное заключение отправлено в PACS")
    sr = None
    for sid in hp.get(f"/studies/{cur_orthanc}").json()["Series"]:
        se = hp.get(f"/series/{sid}").json()
        if se["MainDicomTags"].get("Modality") == "SR":
            sr = hp.get(f"/instances/{se['Instances'][0]}/simplified-tags").json()
    step(sr is not None and sr.get("StudyInstanceUID") == cur_uid,
         "DICOM SR лёг к исходному исследованию в H-PACS")
    step(sr is not None and sr.get("PatientID") == mrn and sr.get("PatientName") == "СИНТЕТИКОВ^ТЕСТ^РЕБЁНОК"
         and sr.get("VerificationFlag") == "VERIFIED",
         "в SR — исходный пациент (кириллица цела), статус VERIFIED")

    failed = [t for ok, t in results if not ok]
    print(f"\nИтог: {len(results) - len(failed)} из {len(results)} шагов"
          + (" — всё в порядке" if not failed else " — есть ошибки"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
