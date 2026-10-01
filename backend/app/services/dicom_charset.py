"""Кодировка текста DICOM на входе: кириллица и узбекская латиница без «кракозябр».

Многие аппараты в СНГ пишут кириллицу в UTF-8 или Windows-1251, не указав
SpecificCharacterSet. pydicom тогда читает байты как Latin-1 — ФИО пациента и описание
исследования превращаются в «Ðåíòãåí…», а при записи могут стать «??????». ФИО нужно
идентифицирующему контуру (заключение в PACS), описание — врачу в рабочем списке.

normalize_charset приводит набор данных к единому виду: весь текст — str, кодировка —
UTF-8 (ISO_IR 192). Для не объявленной кодировки: строгий UTF-8, иначе — запасная
кодировка учреждения (DICOM_FALLBACK_CHARSET, по умолчанию cp1251). Объявленные
кодировки (ISO_IR 144, ISO_IR 100, ISO 2022 …) декодирует сам pydicom.
"""

from __future__ import annotations

import codecs
import logging

from pydicom.dataset import Dataset
from pydicom.multival import MultiValue
from pydicom.valuerep import PersonName

logger = logging.getLogger(__name__)

TEXT_VRS = {"SH", "LO", "ST", "LT", "UT", "PN", "UC"}
UTF8 = "ISO_IR 192"
# Без объявленной кодировки pydicom декодирует как Latin-1: преобразование обратимо,
# исходные байты восстанавливаются точно.
_AS_READ = "latin-1"


def _declared(ds: Dataset) -> list[str]:
    value = ds.get("SpecificCharacterSet")
    if not value:
        return []
    values = list(value) if isinstance(value, MultiValue | list) else [value]
    return [str(v).strip() for v in values if str(v).strip()]


def _text_elements(ds: Dataset):
    for elem in ds.iterall():  # доступ к элементу декодирует его в текущей кодировке
        if elem.VR in TEXT_VRS and elem.value not in (None, ""):
            yield elem


def _strings(value) -> list[str]:
    items = value if isinstance(value, MultiValue | list) else [value]
    return [str(v) for v in items if v is not None]


def _redecode(value, codec: str):
    def one(v):
        return str(v).encode(_AS_READ).decode(codec)

    if isinstance(value, MultiValue | list):
        return [one(v) for v in value]
    return one(value)


def normalize_charset(ds: Dataset, fallback: str = "cp1251") -> str | None:
    """Привести текст набора данных к UTF-8 на месте.

    Возвращает кодировку, угаданную для не объявленного текста (или None, если
    угадывать не пришлось) — для журнала качества данных аппарата.
    """
    declared = _declared(ds)
    guessed = None
    elements = list(_text_elements(ds))
    if not declared or declared == ["ISO_IR 6"]:
        raw = b"".join(s.encode(_AS_READ, "replace") for e in elements for s in _strings(e.value))
        if any(b >= 0x80 for b in raw):
            try:
                raw.decode("utf-8")
                guessed = "utf-8"
            except UnicodeDecodeError:
                guessed = codecs.lookup(fallback).name
            for elem in elements:
                try:
                    elem.value = _redecode(elem.value, guessed)
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass  # смешанный мусор — оставить как прочитано
            logger.warning("DICOM без SpecificCharacterSet с не-ASCII текстом: принят как %s", guessed)
    # Уже декодированные строки — записать единообразно в UTF-8 (PersonName — как строку,
    # иначе pydicom сохранит исходные байты старой кодировки).
    for elem in elements:
        if elem.VR == "PN":
            elem.value = [str(v) for v in elem.value] if isinstance(elem.value, MultiValue) else str(elem.value)
        elif isinstance(elem.value, PersonName):
            elem.value = str(elem.value)
    ds.SpecificCharacterSet = UTF8
    return guessed
