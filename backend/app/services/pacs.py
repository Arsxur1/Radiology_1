"""Коннектор к внешнему PACS (ТЗ, FR-1: приём и опрос по DICOM/DICOMweb).

Платформа подключается к PACS клиники **на инфраструктуре клиники**, а не из
внешнего контура. Поддерживаются два пути:

  1. Классическое DICOM-сетевое взаимодействие (pynetdicom):
     - C-ECHO  — проверка связи (verification),
     - C-FIND  — запрос списка исследований/серий,
     - C-MOVE  — команда PACS выгрузить исследование на наш приёмный AE (Orthanc raw).
  2. DICOMweb (httpx): QIDO-RS (поиск) и WADO-RS (выгрузка), если PACS его поддерживает.

pynetdicom импортируется лениво — сборка и тесты не требуют сети и самого пакета.
Все идентифицирующие данные, пришедшие из PACS, обезличиваются на границе входа
(SR-9) до попадания в доверенный контур.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PacsNode:
    """Параметры подключения к внешнему PACS."""

    aet: str                 # AE Title удалённого PACS
    host: str                # IP/hostname PACS в сети клиники
    port: int                # DICOM-порт (обычно 104 или 11112)
    local_aet: str = "MEDVIZ_RAW"   # наш AE Title (совпадает с orthanc-raw)
    dicomweb_base_url: str | None = None  # если PACS поддерживает DICOMweb


def default_node_from_settings() -> PacsNode | None:
    """Узел PACS из конфигурации (.env). Возвращает None, если не заполнен.

    Позволяет один раз прописать параметры PACS от заказчика в .env и работать
    без передачи узла в каждом вызове (интеграция «под ключ»).
    """
    from app.core.config import get_settings

    s = get_settings()
    if not s.pacs_configured:
        return None
    return PacsNode(
        aet=s.pacs_aet,
        host=s.pacs_host,
        port=s.pacs_port,
        local_aet=s.pacs_local_aet,
        dicomweb_base_url=s.pacs_dicomweb_url,
    )


@dataclass
class StudyQuery:
    """Критерии C-FIND / QIDO на уровне STUDY. Пустые поля — не фильтруются."""

    patient_id: str | None = None
    study_date: str | None = None       # YYYYMMDD или диапазон YYYYMMDD-YYYYMMDD
    modality: str | None = None
    accession_number: str | None = None
    study_instance_uid: str | None = None

    def to_find_identifier(self):  # pragma: no cover - требует pydicom/pynetdicom
        """Собрать DICOM-идентификатор запроса уровня STUDY."""
        from pydicom.dataset import Dataset

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = self.study_instance_uid or ""
        ds.PatientID = self.patient_id or ""
        ds.StudyDate = self.study_date or ""
        ds.ModalitiesInStudy = self.modality or ""
        ds.AccessionNumber = self.accession_number or ""
        # Поля, которые хотим получить в ответе.
        ds.PatientName = ""
        ds.StudyDescription = ""
        ds.NumberOfStudyRelatedSeries = ""
        return ds

    def to_qido_params(self) -> dict:
        """Параметры QIDO-RS (DICOMweb). Пустые — опускаются."""
        mapping = {
            "PatientID": self.patient_id,
            "StudyDate": self.study_date,
            "ModalitiesInStudy": self.modality,
            "AccessionNumber": self.accession_number,
            "StudyInstanceUID": self.study_instance_uid,
        }
        return {k: v for k, v in mapping.items() if v}


@dataclass
class EchoResult:
    ok: bool
    detail: str


@dataclass
class FoundStudy:
    study_instance_uid: str
    patient_id: str | None
    study_date: str | None
    modality: str | None
    description: str | None
    series_count: int | None = None


@dataclass
class QueryOutcome:
    studies: list[FoundStudy] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PacsUnavailable(Exception):
    """PACS недоступен или библиотека DICOM-сети не установлена."""


def _require_pynetdicom():  # pragma: no cover - требует установленного пакета
    try:
        import pynetdicom  # noqa: F401
    except Exception as e:  # noqa: BLE001
        raise PacsUnavailable(
            "pynetdicom не установлен. Установите зависимости PACS-коннектора: "
            "pip install -e '.[pacs]'"
        ) from e


def echo(node: PacsNode, timeout: int = 10) -> EchoResult:  # pragma: no cover - сеть
    """C-ECHO: проверка связи с PACS (verification SOP)."""
    _require_pynetdicom()
    from pynetdicom import AE
    from pynetdicom.sop_class import Verification

    ae = AE(ae_title=node.local_aet)
    ae.add_requested_context(Verification)
    assoc = ae.associate(node.host, node.port, ae_title=node.aet)
    if not assoc.is_established:
        return EchoResult(False, f"Не удалось установить ассоциацию с {node.aet}@{node.host}:{node.port}")
    try:
        status = assoc.send_c_echo()
        ok = bool(status) and status.Status == 0x0000
        return EchoResult(ok, "C-ECHO успешен" if ok else f"C-ECHO статус: {status}")
    finally:
        assoc.release()


def find_studies(node: PacsNode, query: StudyQuery, timeout: int = 30) -> QueryOutcome:  # pragma: no cover - сеть
    """C-FIND: получить список исследований по критериям."""
    _require_pynetdicom()
    from pynetdicom import AE
    from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind

    ae = AE(ae_title=node.local_aet)
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
    assoc = ae.associate(node.host, node.port, ae_title=node.aet)
    if not assoc.is_established:
        raise PacsUnavailable(f"Нет ассоциации с {node.aet}@{node.host}:{node.port}")

    outcome = QueryOutcome()
    try:
        responses = assoc.send_c_find(
            query.to_find_identifier(), StudyRootQueryRetrieveInformationModelFind
        )
        for status, identifier in responses:
            if status and status.Status in (0xFF00, 0xFF01) and identifier is not None:
                outcome.studies.append(
                    FoundStudy(
                        study_instance_uid=str(getattr(identifier, "StudyInstanceUID", "")),
                        patient_id=str(getattr(identifier, "PatientID", "")) or None,
                        study_date=str(getattr(identifier, "StudyDate", "")) or None,
                        modality=str(getattr(identifier, "ModalitiesInStudy", "")) or None,
                        description=str(getattr(identifier, "StudyDescription", "")) or None,
                        series_count=_safe_int(getattr(identifier, "NumberOfStudyRelatedSeries", None)),
                    )
                )
    finally:
        assoc.release()
    return outcome


def move_study(
    node: PacsNode, study_instance_uid: str, destination_aet: str | None = None
) -> bool:  # pragma: no cover - сеть
    """C-MOVE: попросить PACS отправить исследование на наш приёмный AE (Orthanc raw).

    destination_aet по умолчанию — наш local_aet; PACS должен знать его как
    зарегистрированного адресата (это настраивается в самом PACS).
    """
    _require_pynetdicom()
    from pydicom.dataset import Dataset
    from pynetdicom import AE
    from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelMove

    dest = destination_aet or node.local_aet
    ae = AE(ae_title=node.local_aet)
    ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
    assoc = ae.associate(node.host, node.port, ae_title=node.aet)
    if not assoc.is_established:
        raise PacsUnavailable(f"Нет ассоциации с {node.aet}@{node.host}:{node.port}")

    ds = Dataset()
    ds.QueryRetrieveLevel = "STUDY"
    ds.StudyInstanceUID = study_instance_uid
    ok = True
    try:
        for status, _ in assoc.send_c_move(ds, dest, StudyRootQueryRetrieveInformationModelMove):
            if status and status.Status not in (0x0000, 0xFF00):
                ok = False
    finally:
        assoc.release()
    return ok


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
