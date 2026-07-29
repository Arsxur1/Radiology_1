"""Тесты коннектора PACS (ТЗ, FR-1). Чистая логика без сети."""

import pytest

from app.services.pacs import PacsNode, PacsUnavailable, StudyQuery, _require_pynetdicom
from app.services.pacs_dicomweb import _parse_qido_study, _tag


def test_qido_params_omit_empty():
    q = StudyQuery(patient_id="MRN-1", modality="CT")
    params = q.to_qido_params()
    assert params == {"PatientID": "MRN-1", "ModalitiesInStudy": "CT"}
    assert "StudyDate" not in params  # пустые не отправляются


def test_qido_params_all_empty():
    assert StudyQuery().to_qido_params() == {}


def test_node_defaults():
    node = PacsNode(aet="REMOTE", host="10.0.0.5", port=11112)
    assert node.local_aet == "MEDVIZ_RAW"  # совпадает с приёмным Orthanc
    assert node.dicomweb_base_url is None


def test_qido_tag_extraction_pn():
    item = {"00100010": {"vr": "PN", "Value": [{"Alphabetic": "Ivanov^Petr"}]}}
    assert _tag(item, "00100010") == "Ivanov^Petr"


def test_qido_tag_missing():
    assert _tag({}, "00100020") is None


def test_parse_qido_study():
    item = {
        "0020000D": {"Value": ["1.2.3"]},
        "00100020": {"Value": ["MRN-1"]},
        "00080061": {"Value": ["CT"]},
        "00201206": {"Value": ["3"]},
    }
    study = _parse_qido_study(item)
    assert study.study_instance_uid == "1.2.3"
    assert study.patient_id == "MRN-1"
    assert study.modality == "CT"
    assert study.series_count == 3


def test_require_pynetdicom_raises_when_absent():
    # Без установленного pynetdicom коннектор даёт явную ошибку, а не падает молча.
    try:
        import pynetdicom  # noqa: F401
    except Exception:
        with pytest.raises(PacsUnavailable):
            _require_pynetdicom()
