"""Диагностика подключения PACS: на каждом уровне — понятная причина и что сделать (FR-1)."""

from __future__ import annotations

import pytest

pynetdicom = pytest.importorskip("pynetdicom")

from pydicom.dataset import Dataset  # noqa: E402
from pynetdicom import AE, evt  # noqa: E402
from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind, Verification  # noqa: E402

from app.services import pacs_diagnose as d  # noqa: E402
from app.services.pacs import PacsNode  # noqa: E402
from tests.test_pacs_scp import _free_port  # noqa: E402


@pytest.fixture
def scp():
    """Запустить узел с заданными требованиями к AE; вернуть его порт."""
    servers = []

    def start(aet="PACS", *, allowed_calling=None, find_status=None, verification=True):
        ae = AE(ae_title=aet)
        ae.require_called_aet = True
        if allowed_calling is not None:
            ae.require_calling_aet = allowed_calling
        if verification:
            ae.add_supported_context(Verification)
        ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)

        def on_find(event):
            if find_status is not None:
                yield find_status, None
                return
            for i in range(3):
                r = Dataset()
                r.QueryRetrieveLevel = "STUDY"
                r.StudyInstanceUID = f"1.2.3.{i}"
                r.PatientName = "Real^Name"            # не должно попасть в вывод
                yield 0xFF00, r

        port = _free_port()
        servers.append(ae.start_server(("127.0.0.1", port), block=False,
                                       evt_handlers=[(evt.EVT_C_FIND, on_find)]))
        return port

    yield start
    for s in servers:
        s.shutdown()


def test_all_green(scp):
    node = PacsNode(aet="PACS", host="127.0.0.1", port=scp(), local_aet="MEDVIZ_RAW")
    assert d.check_settings(node).ok
    assert d.check_tcp(node).ok
    echo = d.check_echo(node)
    assert echo.ok and echo.detail == "PACS отвечает"
    find = d.check_find(node, "20260930")
    assert find.ok and find.detail.endswith(": 3")
    assert "Real" not in find.detail                       # данные пациентов не выводятся


def test_our_ae_unknown_to_pacs(scp):
    node = PacsNode(aet="PACS", host="127.0.0.1", port=scp(allowed_calling=["SOMEONE_ELSE"]),
                    local_aet="MEDVIZ_RAW")
    step = d.check_echo(node)
    assert not step.ok and "calling AE not recognized" in step.detail
    assert "MEDVIZ_RAW" in step.remedy and "4242" in step.remedy


def test_wrong_pacs_aet(scp):
    node = PacsNode(aet="TYPO", host="127.0.0.1", port=scp("PACS"), local_aet="MEDVIZ_RAW")
    step = d.check_echo(node)
    assert not step.ok and "called AE not recognized" in step.detail and "PACS_AET" in step.remedy


def test_closed_port_and_missing_settings():
    node = PacsNode(aet="PACS", host="127.0.0.1", port=_free_port(), local_aet="MEDVIZ_RAW")
    tcp = d.check_tcp(node, timeout=2)
    assert not tcp.ok and tcp.remedy
    missing = d.check_settings(None)
    assert not missing.ok and ".env" in missing.remedy


def test_find_refused(scp):
    node = PacsNode(aet="PACS", host="127.0.0.1", port=scp(find_status=0xA700), local_aet="MEDVIZ_RAW")
    step = d.check_find(node, "20260930")
    assert not step.ok and "0xA700" in step.detail and "C-FIND" in step.remedy


def test_receiver(scp):
    assert d.check_receiver("127.0.0.1", scp("MEDVIZ_RAW"), "MEDVIZ_RAW").ok
    down = d.check_receiver("127.0.0.1", _free_port(), "MEDVIZ_RAW", timeout=2)
    assert not down.ok and "4242" in down.remedy
