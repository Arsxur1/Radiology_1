"""Ссылки документов на тесты и документы существуют (файл рисков, техфайл, трассируемость).

Документы для регулятора ссылаются на проверку каждой меры. Ссылка на несуществующий тест —
мера, которая выглядит проверенной, но не проверена; так однажды уже было (два неточных имени
в техфайле, журнал 2 октября).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["UPRAVLENIE-RISKAMI.md", "TEKHNICHESKIY-FAYL.md", "TRACEABILITY.md", "KHRANENIE-DANNYKH.md",
        "PRILOZHENIE-DANNYE-NCMC.md", "YUZABILITI.md"]
TESTS = {p.name for p in (ROOT / "backend" / "tests").glob("test_*.py")}
DOC_NAMES = {p.name for p in (ROOT / "docs").glob("*.md")} | {"README.md"}


@pytest.mark.parametrize("doc", DOCS)
def test_referenced_tests_and_docs_exist(doc):
    text = (ROOT / "docs" / doc).read_text(encoding="utf-8")
    names = set(re.findall(r"`([^`\s]+)`", text))
    missing_tests = sorted(n for n in names if re.fullmatch(r"test_\w+\.py", n) and n not in TESTS)
    missing_docs = sorted(n for n in names if re.fullmatch(r"[A-Z][A-Z0-9-]+\.md", n) and n not in DOC_NAMES)
    assert not missing_tests, f"{doc}: нет тестов {missing_tests}"
    assert not missing_docs, f"{doc}: нет документов {missing_docs}"


def test_risk_file_covers_every_hazard_in_summary():
    """Каждая опасность R-NN из анализа попадает в сводку остаточного риска ровно один раз."""
    text = (ROOT / "docs" / "UPRAVLENIE-RISKAMI.md").read_text(encoding="utf-8")
    hazards = set(re.findall(r"\*\*(R-\d\d)\.", text))
    summary = text.split("## 4. Сводка остаточного риска", 1)[1].split("**Общий остаточный риск.**", 1)[0]
    listed = re.findall(r"R-\d\d", summary)
    assert hazards and sorted(listed) == sorted(hazards), (sorted(hazards), sorted(listed))
