"""Пошаговая диагностика подключения PACS клиники (FR-1, чек-лист пилота).

Когда «не работает», ИТ нужно знать, на каком уровне: настройки, сеть (межсетевой экран),
AE Title, права на запросы. Каждый шаг даёт итог и **что сделать**. Данные пациентов не
выводятся: C-FIND возвращает только число найденных исследований.
"""

from __future__ import annotations

import socket
from dataclasses import asdict, dataclass

from app.services.pacs import PacsNode

# A-ASSOCIATE-RJ (DICOM PS3.8, 9.3.4): (источник, причина) → пояснение и что сделать.
_REJECT = {
    (1, 3): ("PACS не знает наш AE Title (calling AE not recognized)",
             "В PACS добавить узел: AE {local} / IP сервера платформы / порт 4242."),
    (1, 7): ("PACS не признаёт вызываемый AE Title (called AE not recognized)",
             "Проверить PACS_AET в .env — точное имя AE PACS, с учётом регистра."),
    (1, 2): ("PACS не поддерживает контекст приложения", "Сообщить разработчикам (нестандартный PACS)."),
    (3, 1): ("PACS временно перегружен", "Повторить позже."),
    (3, 2): ("Превышен лимит ассоциаций PACS", "Повторить позже или увеличить лимит в PACS."),
}


@dataclass
class Step:
    name: str
    ok: bool | None          # None — пропущен
    detail: str
    remedy: str = ""


def _associate(node: PacsNode, contexts: list, timeout: int):
    """Ассоциация с захватом ответа PACS (результат, источник и причина отказа)."""
    from pynetdicom import AE, evt

    seen: dict = {}

    def on_acse(event):
        prim = event.primitive
        if getattr(prim, "result", None) is not None:
            seen.update(result=prim.result, source=getattr(prim, "result_source", None),
                        reason=getattr(prim, "diagnostic", None))

    ae = AE(ae_title=node.local_aet)
    ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = timeout
    for c in contexts:
        ae.add_requested_context(c)
    assoc = ae.associate(node.host, node.port, ae_title=node.aet, evt_handlers=[(evt.EVT_ACSE_RECV, on_acse)])
    return assoc, seen


def _assoc_failure(node: PacsNode, assoc, seen: dict) -> tuple[str, str]:
    if assoc.is_rejected:
        key = (seen.get("source"), seen.get("reason"))
        text, fix = _REJECT.get(key, (f"PACS отклонил ассоциацию (источник {key[0]}, причина {key[1]})",
                                      "Проверить в PACS разрешённые узлы и AE Title."))
        return text, fix.format(local=node.local_aet)
    if assoc.is_aborted:
        return ("PACS прервал соединение", "Проверить в журнале PACS причину и права узла "
                f"{node.local_aet}.")
    return ("Нет ответа на уровне DICOM", "Проверить, что на этом порту действительно DICOM PACS.")


def check_settings(node: PacsNode | None) -> Step:
    if node is None:
        return Step("Настройки", False, "PACS_AET / PACS_HOST / PACS_PORT не заполнены",
                    "Заполнить в .env параметры PACS от ИТ клиники, затем перезапустить backend.")
    return Step("Настройки", True, f"PACS {node.aet} @ {node.host}:{node.port}, наш AE {node.local_aet}")


def check_tcp(node: PacsNode, timeout: float = 5) -> Step:
    try:
        with socket.create_connection((node.host, node.port), timeout=timeout):
            return Step("Сеть (TCP)", True, f"порт {node.host}:{node.port} открыт")
    except TimeoutError:
        return Step("Сеть (TCP)", False, "нет ответа (таймаут)",
                    "Межсетевой экран/маршрут: открыть доступ с сервера платформы к PACS на этот порт.")
    except OSError as e:
        return Step("Сеть (TCP)", False, f"соединение отклонено: {e.strerror or e}",
                    "Проверить IP и порт PACS; на PACS должен слушать DICOM-порт.")


def check_echo(node: PacsNode, timeout: int = 10) -> Step:
    from pynetdicom.sop_class import Verification

    assoc, seen = _associate(node, [Verification], timeout)
    if not assoc.is_established:
        text, fix = _assoc_failure(node, assoc, seen)
        return Step("C-ECHO", False, text, fix)
    try:
        status = assoc.send_c_echo()
        ok = bool(status) and status.Status == 0x0000
        return Step("C-ECHO", ok, "PACS отвечает" if ok else f"статус {status}",
                    "" if ok else "PACS принял соединение, но отклонил проверку — права узла.")
    finally:
        assoc.release()


def check_find(node: PacsNode, study_date: str, timeout: int = 30) -> Step:
    """C-FIND за дату: только число исследований (без данных пациентов)."""
    from pydicom.dataset import Dataset
    from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind as Find

    assoc, seen = _associate(node, [Find], timeout)
    if not assoc.is_established:
        text, fix = _assoc_failure(node, assoc, seen)
        return Step("C-FIND (поиск прошлых исследований)", False, text, fix)
    q = Dataset()
    q.QueryRetrieveLevel = "STUDY"
    q.StudyDate = study_date
    q.StudyInstanceUID = ""
    n, bad = 0, None
    try:
        for status, ident in assoc.send_c_find(q, Find):
            if status and status.Status in (0xFF00, 0xFF01) and ident is not None:
                n += 1
            elif status and status.Status not in (0x0000, 0xFF00, 0xFF01):
                bad = status.Status
    finally:
        assoc.release()
    if bad is not None:
        return Step("C-FIND (поиск прошлых исследований)", False, f"PACS вернул статус 0x{bad:04X}",
                    f"Разрешить в PACS запросы C-FIND для {node.local_aet}.")
    return Step("C-FIND (поиск прошлых исследований)", True, f"исследований за {study_date}: {n}")


# Кодировки, в которых PACS может передать кириллицу (описания исследований, ФИО).
CYRILLIC_CHARSETS = {"ISO_IR 192", "ISO_IR 144", "ISO 2022 IR 144"}


def charset_verdict(charsets: set[str], answered: int) -> Step:
    """Вывод по кодировкам ответов C-FIND (чистая функция — тестируется без PACS)."""
    name = "Кодировка ответов PACS (кириллица)"
    if not answered:
        return Step(name, None, "за неделю нет исследований — кодировку не проверить")
    if charsets & CYRILLIC_CHARSETS:
        return Step(name, True, "ответы с кириллицей: " + ", ".join(sorted(charsets & CYRILLIC_CHARSETS)))
    shown = ", ".join(sorted(charsets)) if charsets else "кодировка не указана"
    return Step(name, False,
                f"PACS отвечает на поиск в «{shown}» — в ней нет кириллицы: описания прошлых "
                "исследований врач увидит без русских и узбекских букв",
                "Включить в PACS ответы на C-FIND в UTF-8 (ISO_IR 192) или кириллице (ISO_IR 144): "
                "настройка кодировки DICOM / Character Set (у Orthanc — DefaultEncoding: Utf8). "
                "Сами снимки это не затрагивает: их кодировка проверяется при приёме.")


def check_find_charset(node: PacsNode, today: str, timeout: int = 30) -> Step:
    """C-FIND за неделю с запросом UTF-8: в какой кодировке PACS отдаёт описания.

    Найдено на эмуляторе H-PACS 13 октября: PACS в Latin-1 заменяет кириллицу пробелами ещё до
    ответа, и на нашей стороне её не восстановить — только настройкой PACS.
    """
    from datetime import datetime, timedelta

    from pydicom.dataset import Dataset
    from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind as Find

    end = datetime.strptime(today, "%Y%m%d")
    q = Dataset()
    q.SpecificCharacterSet = "ISO_IR 192"
    q.QueryRetrieveLevel = "STUDY"
    q.StudyDate = f"{(end - timedelta(days=7)):%Y%m%d}-{end:%Y%m%d}"
    q.StudyInstanceUID = ""
    q.StudyDescription = ""
    assoc, seen = _associate(node, [Find], timeout)
    if not assoc.is_established:
        text, fix = _assoc_failure(node, assoc, seen)
        return Step("Кодировка ответов PACS (кириллица)", False, text, fix)
    charsets: set[str] = set()
    answered = 0
    try:
        for status, ident in assoc.send_c_find(q, Find):
            if status and status.Status in (0xFF00, 0xFF01) and ident is not None:
                answered += 1
                cs = ident.get("SpecificCharacterSet")
                values = [cs] if isinstance(cs, str) else list(cs or [])   # одно значение или несколько
                charsets.update(str(v).strip() for v in values if v)
    finally:
        assoc.release()
    return charset_verdict(charsets, answered)


def check_receiver(host: str, port: int, aet: str, timeout: int = 10) -> Step:
    """Наш приёмник (orthanc-raw) слушает DICOM — сюда PACS шлёт снимки."""
    node = PacsNode(aet=aet, host=host, port=port, local_aet="MEDVIZ_CHECK")
    tcp = check_tcp(node, timeout)
    if not tcp.ok:
        return Step("Наш приёмник DICOM", False, f"{host}:{port} — {tcp.detail}",
                    "Запустить стек (make up); порт 4242 должен быть открыт для IP PACS.")
    echo = check_echo(node, timeout)
    return Step("Наш приёмник DICOM", echo.ok, f"{aet} @ {host}:{port} — {echo.detail}", echo.remedy)


def as_dicts(steps: list[Step]) -> list[dict]:
    return [asdict(s) for s in steps]
