"""Текст, впечатанный в пиксели (SR-9): серия помечается, в обучение и отчёты не идёт."""

from __future__ import annotations

from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.idmap import IdMapBase
from app.models.imaging import Series
from app.models.ml import Report
from app.services import ingest
from app.services.anonymization import anonymize_dataset, burned_in_risk
from app.services.site_data_report import build_site_data_report
from app.services.site_labels import site_manifest
from app.workers.dicom_meta import extract_series_meta, extract_study_meta

DX = "1.2.840.10008.5.1.4.1.1.1.1"
SC = "1.2.840.10008.5.1.4.1.1.7"


def _ds(series_uid: str, study_uid: str, *, sop=DX, flag=None) -> Dataset:
    ds = Dataset()
    ds.PatientID, ds.PatientName = "MRN-1", "Test^Child"
    ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.SOPInstanceUID = study_uid, series_uid, generate_uid()
    ds.SOPClassUID, ds.Modality, ds.PatientAge, ds.Manufacturer = sop, "DX", "005Y", "SynthCo"
    if flag:
        ds.BurnedInAnnotation = flag
    return ds


def _ingest(db, idmap, ds):
    clean, plan = anonymize_dataset(ds)
    tags = {e.keyword: str(e.value) for e in clean if e.keyword}
    meta = extract_series_meta(tags)
    meta["burned_in_risk"] = burned_in_risk(ds)
    out = ingest.persist_ingest(db, idmap, plan=plan, study_meta=extract_study_meta(tags), series_meta=meta)
    db.commit()
    return out


def test_detection():
    assert burned_in_risk(_ds("1", "2", flag="YES"))
    assert burned_in_risk(_ds("1", "2", sop=SC))
    assert burned_in_risk(_ds("1", "2", sop=SC + ".4"))          # многокадровые копии экрана
    assert not burned_in_risk(_ds("1", "2", flag="NO"))
    assert not burned_in_risk(_ds("1", "2"))


def test_flag_spreads_to_series_and_excluded_from_training(db):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    IdMapBase.metadata.create_all(eng)
    idmap = sessionmaker(bind=eng)()
    study_uid, risky, clean_series = generate_uid(), generate_uid(), generate_uid()
    _ingest(db, idmap, _ds(risky, study_uid))                      # первый снимок серии — без флага
    out = _ingest(db, idmap, _ds(risky, study_uid, flag="YES"))   # второй — с надписью
    _ingest(db, idmap, _ds(clean_series, study_uid))
    flagged = {s.series_instance_uid: s.burned_in_risk for s in db.query(Series).all()}
    assert sorted(flagged.values()) == [False, True]
    db.add(Report(study_id=out.study_id, draft_text="", finalized_by="dr"))
    db.commit()
    records, report = site_manifest(db)
    risky_uid = db.query(Series).filter_by(burned_in_risk=True).one().series_instance_uid
    clean_uid = db.query(Series).filter_by(burned_in_risk=False).one().series_instance_uid
    considered = {r["image_id"] for r in records}
    assert risky_uid not in considered                              # в обучение не идёт
    # Чистая серия идёт в обучение (подписанное заключение без находок = «норма»).
    assert considered == {clean_uid} and report["records"] == 1
    site = build_site_data_report(db)
    assert site["per_device"][0]["burned_in_risk"] == 1
    assert any("впечатывает ли аппарат ФИО" in i for i in site["issues"])
