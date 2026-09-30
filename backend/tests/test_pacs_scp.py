"""Коннектор PACS против настоящего DICOM-узла (FR-1).

В тесте поднимаются два узла pynetdicom на localhost:
  - «H-PACS»: Verification, Study Root C-FIND и C-MOVE;
  - «orthanc-raw»: приёмник C-STORE, куда PACS отправляет исследование по C-MOVE.
Так проверяется весь сетевой путь коннектора без внешней сети и без реальных данных.
"""

from __future__ import annotations

import socket

import pytest

pynetdicom = pytest.importorskip("pynetdicom")

from pydicom.dataset import Dataset, FileMetaDataset  # noqa: E402
from pydicom.uid import ExplicitVRLittleEndian, generate_uid  # noqa: E402
from pynetdicom import AE, evt  # noqa: E402
from pynetdicom.sop_class import (  # noqa: E402
    CTImageStorage,
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove,
    Verification,
)

from app.services import pacs  # noqa: E402
from app.services.pacs import PacsNode, StudyQuery  # noqa: E402

PACS_AET, RAW_AET = "HPACS", "MEDVIZ_RAW"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _instance(study_uid: str, patient_id: str, date: str, modality: str = "CT", n: int = 1) -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = CTImageStorage
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = generate_uid()
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = study_uid + ".1"
    ds.PatientID = patient_id
    ds.PatientName = "Test^Synthetic"
    ds.StudyDate = date
    ds.Modality = modality
    ds.StudyDescription = "Synthetic study"
    ds.InstanceNumber = n
    return ds


@pytest.fixture
def dicom_net():
    """Тестовый PACS с двумя исследованиями одного пациента и одним — другого."""
    archive = {
        "1.2.826.0.1.1": [_instance("1.2.826.0.1.1", "MRN-7", "20250101", n=i) for i in (1, 2)],
        "1.2.826.0.1.2": [_instance("1.2.826.0.1.2", "MRN-7", "20260315", "MR")],
        "1.2.826.0.1.3": [_instance("1.2.826.0.1.3", "MRN-8", "20260316")],
    }
    received: list[Dataset] = []
    raw_port, pacs_port = _free_port(), _free_port()

    def on_store(event):
        received.append(event.dataset)
        return 0x0000

    raw = AE(ae_title=RAW_AET)
    raw.add_supported_context(CTImageStorage, ExplicitVRLittleEndian)
    raw_srv = raw.start_server(("127.0.0.1", raw_port), block=False, evt_handlers=[(evt.EVT_C_STORE, on_store)])

    def on_find(event):
        q = event.identifier
        for uid, instances in archive.items():
            first = instances[0]
            if q.get("PatientID") and q.PatientID != first.PatientID:
                continue
            if q.get("StudyInstanceUID") and q.StudyInstanceUID != uid:
                continue
            r = Dataset()
            r.QueryRetrieveLevel = "STUDY"
            r.StudyInstanceUID = uid
            r.PatientID = first.PatientID
            r.PatientName = first.PatientName
            r.StudyDate = first.StudyDate
            r.ModalitiesInStudy = first.Modality
            r.StudyDescription = first.StudyDescription
            r.NumberOfStudyRelatedSeries = 1
            yield 0xFF00, r

    def on_move(event):
        if event.move_destination.strip() != RAW_AET:
            yield None, None   # неизвестный адресат
            return
        yield "127.0.0.1", raw_port
        instances = archive.get(event.identifier.StudyInstanceUID, [])
        yield len(instances)
        for ds in instances:
            yield 0xFF00, ds

    hpacs = AE(ae_title=PACS_AET)
    hpacs.add_supported_context(Verification)
    hpacs.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
    hpacs.add_supported_context(StudyRootQueryRetrieveInformationModelMove)
    hpacs.add_requested_context(CTImageStorage, ExplicitVRLittleEndian)
    pacs_srv = hpacs.start_server(("127.0.0.1", pacs_port), block=False,
                                  evt_handlers=[(evt.EVT_C_FIND, on_find), (evt.EVT_C_MOVE, on_move)])
    node = PacsNode(aet=PACS_AET, host="127.0.0.1", port=pacs_port, local_aet=RAW_AET)
    try:
        yield node, received
    finally:
        pacs_srv.shutdown()
        raw_srv.shutdown()


def test_echo(dicom_net):
    node, _ = dicom_net
    result = pacs.echo(node)
    assert result.ok, result.detail


def test_echo_unreachable_node():
    node = PacsNode(aet="NOPE", host="127.0.0.1", port=_free_port())
    assert pacs.echo(node).ok is False


def test_find_by_patient(dicom_net):
    node, _ = dicom_net
    found = pacs.find_studies(node, StudyQuery(patient_id="MRN-7"))
    by_uid = {s.study_instance_uid: s for s in found.studies}
    assert set(by_uid) == {"1.2.826.0.1.1", "1.2.826.0.1.2"}
    assert by_uid["1.2.826.0.1.2"].modality == "MR"
    assert by_uid["1.2.826.0.1.1"].study_date == "20250101"
    assert by_uid["1.2.826.0.1.1"].series_count == 1


def test_move_delivers_study_to_raw(dicom_net):
    node, received = dicom_net
    assert pacs.move_study(node, "1.2.826.0.1.1") is True
    assert len(received) == 2
    assert {d.StudyInstanceUID for d in received} == {"1.2.826.0.1.1"}


def test_move_to_unknown_destination_fails(dicom_net):
    node, received = dicom_net
    assert pacs.move_study(node, "1.2.826.0.1.1", destination_aet="STRANGER") is False
    assert received == []
