"""Происхождение обучающих данных моделей и право на коммерческое применение (ТЗ, вопрос 34).

Модель в ASSIST — часть коммерческого медизделия. Если веса обучены на данных с лицензией
«только для научных исследований», такая модель годится для теневой оценки на площадке, но
не для клинического применения в продукте. Здесь — реестр источников с условиями,
проверенными по первоисточникам (дата и ссылка указаны), и правило для гейта продвижения.

commercial: "yes" — лицензия допускает коммерческое использование; "no" — прямо запрещает
(только исследования); "unknown" — не проверено, решает юрист. Это не юридическое
заключение: окончательное решение — за юристом (PILOT-NCMC, раздел 2).
"""

from __future__ import annotations

from dataclasses import dataclass

CHECKED = "2026-10-01"


@dataclass(frozen=True)
class DataSource:
    key: str
    title: str
    url: str
    access: str
    license: str
    commercial: str          # yes / no / unknown
    note: str = ""


_RESEARCH_ONLY = "только научные исследования («lawful use in scientific research and no other»)"

SOURCES: dict[str, DataSource] = {s.key: s for s in (
    DataSource("nih", "NIH ChestX-ray14", "https://nihcc.app.box.com/v/ChestXray-NIHCC",
               "открытый, без регистрации", "без ограничений использования; обязательны ссылка на NIH, "
               "цитирование CVPR 2017 и указание NIH Clinical Center как поставщика", "yes"),
    DataSource("mimic-cxr-jpg", "MIMIC-CXR-JPG", "https://physionet.org/content/mimic-cxr-jpg/2.1.0/",
               "credentialed: CITI + DUA", "PhysioNet Credentialed Health Data License 1.5.0 — " + _RESEARCH_ONLY,
               "no"),
    DataSource("mimic_ch", "MIMIC-CXR (метки CheXpert)", "https://physionet.org/content/mimic-cxr/",
               "credentialed: CITI + DUA", "PhysioNet Credentialed Health Data License — " + _RESEARCH_ONLY, "no"),
    DataSource("mimic_nb", "MIMIC-CXR (метки NegBio)", "https://physionet.org/content/mimic-cxr/",
               "credentialed: CITI + DUA", "PhysioNet Credentialed Health Data License — " + _RESEARCH_ONLY, "no"),
    DataSource("vindr-cxr", "VinDr-CXR", "https://physionet.org/content/vindr-cxr/1.0.0/",
               "credentialed: CITI + DUA", "PhysioNet Credentialed Health Data License 1.5.0 — " + _RESEARCH_ONLY,
               "no"),
    DataSource("vindr-pcxr", "VinDr-PCXR (дети)", "https://physionet.org/content/vindr-pcxr/1.0.0/",
               "restricted: регистрация + подпись DUA (без CITI)",
               "PhysioNet Restricted Health Data License 1.5.0 — " + _RESEARCH_ONLY, "no",
               "Для научной валидации и публикаций; веса для продукта на нём обучать нельзя."),
    DataSource("pc", "PadChest", "https://bimcv.cipf.es/bimcv-projects/padchest/",
               "регистрация + Research Use Agreement",
               "PADCHEST Dataset Research Use Agreement — только исследования; иное — по согласованию с BIMCV",
               "no"),
    DataSource("chex", "CheXpert", "https://stanfordmlgroup.github.io/competitions/chexpert/",
               "регистрация + соглашение Stanford", "соглашение об исследовательском использовании (не проверено "
               "по первоисточнику)", "unknown"),
    DataSource("google", "NIH ChestX-ray14 (метки Google)", "https://cloud.google.com/healthcare-api/docs/resources/public-datasets/nih-chest",
               "открытый", "условия меток Google не проверены", "unknown"),
    DataSource("openi", "OpenI (Indiana University)", "https://openi.nlm.nih.gov/", "открытый",
               "не проверено", "unknown"),
    DataSource("rsna", "RSNA Pneumonia Detection (на основе NIH)",
               "https://www.kaggle.com/competitions/rsna-pneumonia-detection-challenge", "Kaggle",
               "условия соревнования не проверены", "unknown"),
    DataSource("kermany", "Pediatric CXR (Kermany, Guangzhou)", "https://data.mendeley.com/datasets/rscbjbr9sj/2",
               "открытый, без регистрации", "CC BY 4.0", "yes",
               "5856 снимков детей 1–5 лет; метки — диагнозы «пневмония/норма» (SR-1: не выдавать как "
               "диагноз); пригоден для педиатрической адаптации и проверки «норма/не норма»."),
    DataSource("hwcmc", "HWCMC (Hainan Women and Children's Medical Center)",
               "https://doi.org/10.5281/zenodo.13744272", "открытый (Zenodo)", "CC BY 4.0", "yes",
               "5632 снимка детей 0–14 лет; метки — типы пневмонии и норма (диагнозы, SR-1)."),
    DataSource("pediatric-ct-seg", "Pediatric-CT-SEG (TCIA)", "https://doi.org/10.7937/TCIA.X0H0-1706",
               "открытый (TCIA / IDC)", "лицензия коллекции TCIA не проверена (сайт недоступен из среды "
               "разработки)", "unknown",
               "359 КТ детей 5 дней – 16 лет, до 29 структур экспертами: эталон для педиатрической "
               "проверки сегментации КТ."),
    DataSource("imagenet", "ImageNet (предобучение torchvision)", "https://www.image-net.org/download.php",
               "открытый", "веса torchvision — BSD; условия ImageNet для обученных на нём весов юристы "
               "трактуют по-разному", "unknown", "Стартовые веса train.py (--pretrained imagenet)."),
    DataSource("totalsegmentator", "TotalSegmentator: задачи total / total_mr",
               "https://github.com/wasserth/TotalSegmentator", "открытый",
               "веса — Apache-2.0 («openly available for any usage»), включая --fast; обучающие наборы "
               "на Zenodo (CT v3, MRI v3) — CC BY 4.0", "yes",
               "Прочие задачи (heartchambers_highres, appendicular_bones, tissue_types…) — по лицензии."),
    DataSource("ncmc", "Собственные данные площадки (NCMC)", "", "внутренний контур клиники",
               "договор с клиникой и правовое основание обработки", "yes",
               "Условие — договор с NCMC; хранение в Узбекистане (закон о персональных данных, ст. 27-1)."),
)}

# Датасеты, на которых обучены веса TorchXRayVision (по исходному коду библиотеки,
# torchxrayvision/models.py, model_urls[...]["description"]; для одиночных весов — по имени).
XRV_TRAINING_DATA: dict[str, tuple[str, ...]] = {
    "densenet121-res224-all": ("nih", "pc", "chex", "mimic_ch", "google", "openi", "rsna"),
    "densenet121-res224-nih": ("nih",),
    "densenet121-res224-pc": ("pc",),
    "densenet121-res224-chex": ("chex",),
    "densenet121-res224-mimic_nb": ("mimic_nb",),
    "densenet121-res224-mimic_ch": ("mimic_ch",),
}


def training_data_of(adapter: dict | None, declared: list[str] | None) -> list[str]:
    """Ключи источников обучающих данных модели: по адаптеру открытой модели или из карточки."""
    adapter = adapter or {}
    if adapter.get("type") == "xrv":
        return list(XRV_TRAINING_DATA.get(adapter.get("weights", ""), ()))
    if adapter.get("type") == "totalsegmentator":
        return ["totalsegmentator"]
    return list(declared or [])


def assess(adapter: dict | None, declared: list[str] | None) -> dict:
    """Итог по коммерческому применению: commercial = yes / no / unknown, с причинами."""
    keys = training_data_of(adapter, declared)
    sources = [SOURCES.get(k) for k in keys]
    research_only = [s.title for s in sources if s and s.commercial == "no"]
    unknown = [s.title for s in sources if s and s.commercial == "unknown"] + \
        [k for k, s in zip(keys, sources, strict=True) if s is None]
    if not keys:
        status, unknown = "unknown", ["происхождение обучающих данных не указано"]
    elif research_only:
        status = "no"
    elif unknown:
        status = "unknown"
    else:
        status = "yes"
    return {"training_data": keys, "commercial": status, "research_only": research_only,
            "unverified": unknown, "checked": CHECKED}


def gate_reason(assessment: dict) -> str | None:
    """Причина отказа гейта: модель на данных «только для исследований» в ASSIST не идёт."""
    if assessment["commercial"] != "no":
        return None
    return ("Веса обучены на данных с лицензией «только для научных исследований» ("
            + ", ".join(assessment["research_only"]) + "): клиническое применение в коммерческом "
            "медизделии запрещено. Для ASSIST — веса на открытых коммерчески допустимых данных "
            "(например, xrv densenet121-res224-nih) или дообучение на данных площадки.")
