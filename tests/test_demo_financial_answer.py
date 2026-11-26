"""The offline demonstration must answer a question, not only import evidence.

The demonstration's Apple payload is XBRL facts; the answer engine reads statement tables out of
ingested filings. Without a parsed filing the demo could be installed, run end to end, and still
offer no certificate — which is the one surface the research interface is built around. These
tests pin the answer section and the provenance rule that decided whether its report may be
exported.
"""

from __future__ import annotations

import pytest

from atlas.demo import run_demo
from atlas.research.memo import ResearchMemoService
from atlas.storage.db import Database

APPLE = "ISS-CIK0000320193"


@pytest.fixture(scope="module")
def demo_database(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("demo") / "demo.db"
    run_demo(db_path=str(path), stream=lambda _message: None)
    return str(path)


def test_the_offline_demo_issues_an_answer_certificate(demo_database: str) -> None:
    result = run_demo(db_path=demo_database, reset=False, stream=lambda _message: None)
    answer = result["financial_answer"]
    assert answer["status"] == "answered", answer
    # 48,200 net sales less 26,510 cost of sales, in millions, from the synthetic filing.
    assert answer["value"] == "21690", answer
    assert answer["concept"] == "gross_profit"
    assert answer["answer_outcome"] == "answered"
    assert answer["certificate_fingerprint"]
    assert answer["verification"] in {"ARITHMETIC_VERIFIED", "SOURCE_VERIFIED"}


def test_memo_provenance_cites_only_the_sources_it_used(demo_database: str) -> None:
    """A source that exists in the database but underpins nothing must not block an export.

    The demonstration records no user-responsibility rows, so it is a clean case: the memo's
    rights decision must be based on the sources its own company actually rests on.
    """
    database = Database(demo_database)
    try:
        memo = ResearchMemoService(database).build(APPLE)
    finally:
        database.close()
    assert memo["rights"]["blocked_sources"] == [], memo["rights"]
    assert memo["rights"]["redistributable"] is True
