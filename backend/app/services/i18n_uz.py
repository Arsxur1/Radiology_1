"""Узбекские (латиница) названия находок ОГК и анатомических структур для заключений.

ЧЕРНОВОЙ ПЕРЕВОД: требует проверки врачом-рентгенологом — носителем языка до
клинического использования (см. docs/GLOSSARY-UZ.md). Пока UZ_GLOSSARY_APPROVED не
отмечен, интерфейс предупреждает о непроверенной терминологии.

Перевод касается только названий: числа и коды в заключении те же (SR-1: шаблон не
добавляет смыслов).
"""

from __future__ import annotations

UZ_GLOSSARY_APPROVED = False

FINDINGS_UZ: dict[str, str] = {
    "CXR-000": "Patologik o‘zgarishlarsiz",
    "CXR-100": "Konsolidatsiya (zichlashish)",
    "CXR-101": "Infiltratsiya",
    "CXR-102": "Atelektaz / kollaps",
    "CXR-103": "O‘choq / tugun",
    "CXR-104": "Hajmli hosila",
    "CXR-105": "Bo‘shliq / kaverna",
    "CXR-106": "Interstitsial o‘zgarishlar",
    "CXR-107": "Miliar tarqalish",
    "CXR-108": "«Xira shisha» belgisi",
    "CXR-109": "Giperinflyatsiya",
    "CXR-110": "Bronxoektazlar",
    "CXR-111": "Fibroz / chandiqli o‘zgarishlar",
    "CXR-112": "Tugun / hosila (aniqlanmagan)",
    "CXR-113": "Soyalanish (aniqlanmagan)",
    "CXR-114": "O‘pka shishi (rentgenologik belgi)",
    "CXR-115": "Emfizema",
    "CXR-116": "Kalsinat",
    "CXR-117": "O‘pka kistasi",
    "CXR-200": "Plevral bo‘shliqda suyuqlik",
    "CXR-201": "Pnevmotoraks",
    "CXR-202": "Plevraning qalinlashuvi",
    "CXR-203": "Plevradagi boshqa o‘zgarishlar",
    "CXR-300": "Peribronxial o‘zgarishlar",
    "CXR-301": "Nafas yo‘llarining torayishi / siqilishi",
    "CXR-302": "Yot jism",
    "CXR-400": "O‘pka ildizining kengayishi / limfadenopatiya",
    "CXR-401": "Ko‘ks oralig‘ining kengayishi",
    "CXR-402": "Ko‘ks oralig‘i hosilasi",
    "CXR-403": "Aortaning kengayishi",
    "CXR-404": "O‘pka arteriyasining kengayishi",
    "CXR-405": "Ko‘ks oralig‘ining siljishi",
    "CXR-406": "Yurak-ko‘ks oralig‘i soyasining kengayishi",
    "CXR-500": "Kardiomegaliya",
    "CXR-501": "Yurak joylashuvi anomaliyasi / situs",
    "CXR-600": "Qovurg‘a sinishi",
    "CXR-601": "Skolioz / ko‘krak qafasi deformatsiyasi",
    "CXR-602": "Ko‘krak qafasi suyaklarining sinishi (aniqlanmagan)",
    "CXR-603": "O‘mrov suyagi sinishi",
    "CXR-700": "Endotraxeal naycha holati",
    "CXR-701": "Nazogastral zond holati",
    "CXR-702": "Markaziy kateter holati",
    "CXR-703": "Qurilmalar / kateterlar mavjudligi",
}

STRUCTURES_UZ: dict[str, str] = {
    "lung_upper_lobe_left": "Chap o‘pka yuqori bo‘lagi",
    "lung_lower_lobe_left": "Chap o‘pka pastki bo‘lagi",
    "lung_upper_lobe_right": "O‘ng o‘pka yuqori bo‘lagi",
    "lung_middle_lobe_right": "O‘ng o‘pka o‘rta bo‘lagi",
    "lung_lower_lobe_right": "O‘ng o‘pka pastki bo‘lagi",
    "heart": "Yurak",
    "aorta": "Aorta",
    "trachea": "Traxeya",
    "esophagus": "Qizilo‘ngach",
    "vertebrae_thoracic": "Ko‘krak umurtqalari",
    "liver": "Jigar",
    "spleen": "Taloq",
    "kidney_left": "Chap buyrak",
    "kidney_right": "O‘ng buyrak",
    "pancreas": "Oshqozon osti bezi",
    "gallbladder": "O‘t pufagi",
    "stomach": "Oshqozon",
    "urinary_bladder": "Siydik pufagi",
    "vertebrae_lumbar": "Bel umurtqalari",
    "brain": "Bosh miya",
    "ventricles": "Miya qorinchalari",
    "hippocampus_left": "Chap gippokamp",
    "hippocampus_right": "O‘ng gippokamp",
}


def localized_label(language: str, code: str | None, structure_key: str | None, fallback: str | None) -> str | None:
    """Название для заключения на нужном языке; нет перевода — исходное название."""
    if language != "uz":
        return fallback
    if structure_key and structure_key in STRUCTURES_UZ:
        return STRUCTURES_UZ[structure_key]
    if code and code in FINDINGS_UZ:
        return FINDINGS_UZ[code]
    return fallback
