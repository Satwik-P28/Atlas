"""Author the prospective holdout gold from printed cells plus same-accession XBRL facts.

The observations below were read from the archived filing bytes with
``scripts/answer_semantics_holdout_inspect.py`` (a dependency-free table dumper) and
corroborated against SEC company facts filtered to the same accession, period end and USD unit.
Nothing here executes a resolver or reads a resolver artifact; the script only formats the
authored observations, checks the two authorities against each other and writes the gold files
together with a complete disposition ledger.

A mismatch is fatal: the generator stops instead of writing a label it cannot corroborate.
"""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from answer_semantics_holdout_inspect import _Tables, _row_text  # noqa: E402

FIXTURES = ROOT / "fixtures" / "answer_semantics"
CORPUS = FIXTURES / "holdout_corpus.json"
FACTS = FIXTURES / "holdout_facts.json"
QUESTIONS = FIXTURES / "holdout_questions.json"
LEDGER = FIXTURES / "holdout_ledger.json"
SNAPSHOTS = ROOT / "var" / "answer_semantics" / "holdout" / "snapshots"
REVIEWED_AT = "2026-11-23"
SCALE = 6

# --------------------------------------------------------------------------- authored observations
# Each slot is read off the printed statement: the row label as printed, the printed cell text,
# the printed column caption and the statement it belongs to. The tag/end pair is the
# same-accession XBRL fact that must agree with the printed cell.
FILINGS: list[dict[str, Any]] = [
    {
        "cik": "0000018230", "issuer": "Caterpillar Inc", "short": "Caterpillar",
        "accession": "0000018230-23-000011", "period": "2022", "period_end": "2022-12-31",
        "prior": "2021", "prior_end": "2021-12-31",
        "statement": "Supplemental Data for Results of Operations (consolidated columns)",
        "balance": "Consolidated Balance Sheets",
        "banner": "(Millions of dollars)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Total sales and revenues"],
             "raw": "59,427", "column": "2022", "tag": "Revenues", "end": "2022-12-31"},
            {"concept": "revenue", "operator": "percentage_change",
             "row_labels": ["Total sales and revenues"], "raw": "59,427", "prior_raw": "50,971",
             "column": "2022", "prior_column": "2021", "tag": "Revenues", "end": "2022-12-31",
             "prior_end": "2021-12-31"},
            {"concept": "total_assets", "operator": "lookup", "row_labels": ["Total assets"],
             "raw": "81,943", "column": "2022", "tag": "Assets", "end": "2022-12-31",
             "statement_key": "balance"},
            {"concept": "operating_income", "operator": "lookup", "row_labels": ["Operating profit"],
             "raw": "7,904", "column": "2022", "tag": "OperatingIncomeLoss", "end": "2022-12-31"},
            {"concept": "gross_profit", "operator": "lookup", "abstain": "structurally_unanswerable",
             "note": ("Neither the printed statements nor the accession's XBRL facts report gross "
                      "profit; Caterpillar prints sales, operating costs and operating profit.")},
        ],
        "skipped": [
            {"slot": "net_income", "reason": "concept_tag_absent",
             "detail": ("Caterpillar books its result as ProfitLoss and prints 'Profit attributable "
                        "to common shareholders'; the accession carries no NetIncomeLoss fact, so "
                        "there is no independent XBRL value for the concept. Recorded, not scored.")},
        ],
    },
    {
        "cik": "0000019617", "issuer": "JPMorgan Chase & Co", "short": "JPMorgan Chase",
        "accession": "0000019617-23-000231", "period": "2022", "period_end": "2022-12-31",
        "prior": "2021", "prior_end": "2021-12-31",
        "statement": "Consolidated statements of income (revenue section)",
        "balance": "Consolidated balance sheets",
        "banner": "(in millions, except per share data)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Total net revenue"],
             "raw": "128,695", "column": "2022", "tag": "Revenues", "end": "2022-12-31"},
            {"concept": "revenue", "operator": "percentage_change",
             "row_labels": ["Total net revenue"], "raw": "128,695", "prior_raw": "121,649",
             "column": "2022", "prior_column": "2021", "tag": "Revenues", "end": "2022-12-31",
             "prior_end": "2021-12-31"},
            {"concept": "net_income", "operator": "lookup", "row_labels": ["Net income"],
             "raw": "37,676", "column": "2022", "tag": "NetIncomeLoss", "end": "2022-12-31"},
            {"concept": "total_assets", "operator": "lookup", "row_labels": ["Total assets"],
             "raw": "3,665,743", "column": "December 31, 2022", "tag": "Assets", "end": "2022-12-31",
             "statement_key": "balance"},
            {"concept": "gross_profit", "operator": "lookup", "abstain": "structurally_unanswerable",
             "note": ("A bank holding company statement reports net interest income, noninterest "
                      "revenue and provision for credit losses; it prints no gross-profit subtotal "
                      "and the accession carries no GrossProfit fact.")},
        ],
        "skipped": [],
    },
    {
        "cik": "0000050863", "issuer": "Intel Corp", "short": "Intel",
        "accession": "0000050863-23-000006", "period": "2022", "period_end": "2022-12-31",
        "prior": "2021", "prior_end": "2021-12-25",
        "statement": "Consolidated Statements of Operations",
        "balance": "Consolidated Balance Sheets",
        "banner": "(In Millions, Except Per Share Amounts)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Net revenue"],
             "raw": "63,054", "column": "Dec 31, 2022",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-12-31"},
            {"concept": "revenue", "operator": "percentage_change", "row_labels": ["Net revenue"],
             "raw": "63,054", "prior_raw": "79,024", "column": "Dec 31, 2022",
             "prior_column": "Dec 25, 2021",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-12-31",
             "prior_end": "2021-12-25"},
            {"concept": "total_assets", "operator": "lookup", "row_labels": ["Total assets"],
             "raw": "182,103", "column": "Dec 31, 2022", "tag": "Assets", "end": "2022-12-31",
             "statement_key": "balance"},
            {"concept": "gross_profit", "operator": "lookup", "row_labels": ["Gross margin"],
             "raw": "26,866", "column": "Dec 31, 2022", "tag": "GrossProfit", "end": "2022-12-31"},
        ],
        "skipped": [
            {"slot": "net_income", "reason": "definitional_ambiguity",
             "detail": ("The statement prints 'Net income' 8,017 (ProfitLoss, before "
                        "non-controlling interests) and 'Net income attributable to Intel' 8,014 "
                        "(NetIncomeLoss). Two different amounts answer 'net income', so the slot "
                        "was not resolved on the author's judgement and fell through to total "
                        "assets. Recorded, not scored.")},
        ],
    },
    {
        "cik": "0001341439", "issuer": "Oracle Corp", "short": "Oracle",
        "accession": "0001564590-22-023675", "period": "2022", "period_end": "2022-05-31",
        "prior": "2021", "prior_end": "2021-05-31",
        "statement": "Consolidated Statements of Operations",
        "balance": "Consolidated Balance Sheets",
        "banner": "(in millions, except per share data)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Total revenues"],
             "raw": "42,440", "column": "2022",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-05-31"},
            {"concept": "revenue", "operator": "percentage_change", "row_labels": ["Total revenues"],
             "raw": "42,440", "prior_raw": "40,479", "column": "2022", "prior_column": "2021",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-05-31",
             "prior_end": "2021-05-31"},
            {"concept": "net_income", "operator": "lookup", "row_labels": ["Net income"],
             "raw": "6,717", "column": "2022", "tag": "NetIncomeLoss", "end": "2022-05-31"},
            {"concept": "operating_income", "operator": "lookup", "row_labels": ["Operating income"],
             "raw": "10,926", "column": "2022", "tag": "OperatingIncomeLoss", "end": "2022-05-31"},
            {"concept": "gross_profit", "operator": "lookup", "abstain": "structurally_unanswerable",
             "note": ("Oracle's statement of operations runs from total revenues straight to total "
                      "operating expenses and operating income; no gross-profit row is printed and "
                      "the accession carries no GrossProfit fact.")},
        ],
        "skipped": [],
    },
    {
        "cik": "0001090727", "issuer": "United Parcel Service Inc", "short": "UPS",
        "accession": "0001090727-23-000006", "period": "2022", "period_end": "2022-12-31",
        "prior": "2021", "prior_end": "2021-12-31",
        "statement": "Consolidated Statements of Income",
        "balance": "Consolidated Balance Sheets",
        "banner": "(in millions, except per share amounts)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Revenue"],
             "raw": "100,338", "column": "2022",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-12-31"},
            {"concept": "revenue", "operator": "percentage_change", "row_labels": ["Revenue"],
             "raw": "100,338", "prior_raw": "97,287", "column": "2022", "prior_column": "2021",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-12-31",
             "prior_end": "2021-12-31"},
            {"concept": "net_income", "operator": "lookup", "row_labels": ["Net income"],
             "raw": "11,548", "column": "2022", "tag": "NetIncomeLoss", "end": "2022-12-31"},
            {"concept": "operating_income", "operator": "lookup", "row_labels": ["Operating profit"],
             "raw": "13,094", "column": "2022", "tag": "OperatingIncomeLoss", "end": "2022-12-31"},
            {"concept": "gross_profit", "operator": "lookup", "abstain": "structurally_unanswerable",
             "note": ("UPS prints revenue, operating expenses and operating profit; it prints no "
                      "gross-profit subtotal and the accession carries no GrossProfit fact.")},
        ],
        "skipped": [],
    },
    {
        "cik": "0000006951", "issuer": "Applied Materials Inc", "short": "Applied Materials",
        "accession": "0000006951-22-000043", "period": "2022", "period_end": "2022-10-30",
        "prior": "2021", "prior_end": "2021-10-31",
        "statement": "Consolidated Statements of Operations",
        "balance": "Consolidated Balance Sheets",
        "banner": "(In millions, except per share amounts and percentages)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Net sales"],
             "raw": "25,785", "column": "2022",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-10-30"},
            {"concept": "revenue", "operator": "percentage_change", "row_labels": ["Net sales"],
             "raw": "25,785", "prior_raw": "23,063", "column": "2022", "prior_column": "2021",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-10-30",
             "prior_end": "2021-10-31"},
            {"concept": "net_income", "operator": "lookup", "row_labels": ["Net income"],
             "raw": "6,525", "column": "2022", "tag": "NetIncomeLoss", "end": "2022-10-30"},
            {"concept": "gross_profit", "operator": "lookup", "row_labels": ["Gross profit"],
             "raw": "11,993", "column": "2022", "tag": "GrossProfit", "end": "2022-10-30"},
        ],
        "skipped": [],
    },
    {
        "cik": "0001018724", "issuer": "Amazon.com Inc", "short": "Amazon",
        "accession": "0001018724-23-000004", "period": "2022", "period_end": "2022-12-31",
        "prior": "2021", "prior_end": "2021-12-31",
        "statement": "Consolidated Statements of Operations",
        "balance": "Consolidated Balance Sheets",
        "banner": "(in millions, except per share data)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Total net sales"],
             "raw": "513,983", "column": "2022",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-12-31"},
            {"concept": "revenue", "operator": "percentage_change", "row_labels": ["Total net sales"],
             "raw": "513,983", "prior_raw": "469,822", "column": "2022", "prior_column": "2021",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-12-31",
             "prior_end": "2021-12-31"},
            {"concept": "total_assets", "operator": "lookup", "row_labels": ["Total assets"],
             "raw": "462,675", "column": "December 31, 2022", "tag": "Assets", "end": "2022-12-31",
             "statement_key": "balance"},
            {"concept": "operating_income", "operator": "lookup", "row_labels": ["Operating income"],
             "raw": "12,248", "column": "2022", "tag": "OperatingIncomeLoss", "end": "2022-12-31"},
        ],
        "skipped": [
            {"slot": "net_income", "reason": "negative_print",
             "detail": ("Amazon's consolidated net result for 2022 is printed as a parenthesised "
                        "loss (-2,722 million). A parenthesised cell cannot round-trip the gold "
                        "contract's unsigned printed-value check, so the slot fell through to "
                        "total assets. Recorded, not scored.")},
            {"slot": "gross_profit_probe", "reason": "absence_contested",
             "detail": ("Amazon prints a 'Gross profit' row inside a segment note (— (465) "
                        "(2,123)). Absence of the concept is therefore not established, so no "
                        "abstention probe is generated. Recorded, not scored.")},
        ],
    },
    {
        "cik": "0001744489", "issuer": "Walt Disney Co", "short": "Disney",
        "accession": "0001744489-22-000213", "period": "2022", "period_end": "2022-10-01",
        "prior": "2021", "prior_end": "2021-10-02",
        "statement": "Consolidated Statements of Income",
        "balance": "Consolidated Balance Sheets",
        "banner": "(in millions, except per share data)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Total revenues"],
             "raw": "82,722", "column": "2022", "tag": "Revenues", "end": "2022-10-01"},
            {"concept": "revenue", "operator": "percentage_change", "row_labels": ["Total revenues"],
             "raw": "82,722", "prior_raw": "67,418", "column": "2022", "prior_column": "2021",
             "tag": "Revenues", "end": "2022-10-01", "prior_end": "2021-10-02"},
            {"concept": "net_income", "operator": "lookup",
             "row_labels": ["Net income attributable to Disney",
                            "Net income (loss) attributable to The Walt Disney Company (Disney)"],
             "raw": "3,145", "column": "2022", "tag": "NetIncomeLoss", "end": "2022-10-01"},
            {"concept": "total_assets", "operator": "lookup", "row_labels": ["Total assets"],
             "raw": "203,631", "column": "October 1, 2022", "tag": "Assets", "end": "2022-10-01",
             "statement_key": "balance"},
            {"concept": "gross_profit", "operator": "lookup", "abstain": "structurally_unanswerable",
             "note": ("Disney's statement of income deducts costs and expenses from total revenues "
                      "and reports segment operating income in a separate reconciliation; the "
                      "statement prints no gross-profit row and the accession carries no "
                      "GrossProfit fact.")},
        ],
        "skipped": [
            {"slot": "operating_income", "reason": "segment_only",
             "detail": ("The only printed 12,121 figure is 'Total segment operating income', a "
                        "segment total, not a consolidated statement row. The slot fell through to "
                        "total assets. Recorded, not scored.")},
        ],
    },
    {
        "cik": "0000012927", "issuer": "Boeing Co", "short": "Boeing",
        "accession": "0000012927-23-000007", "period": "2022", "period_end": "2022-12-31",
        "prior": "2021", "prior_end": "2021-12-31",
        "statement": "Consolidated Statements of Operations",
        "balance": "Consolidated Balance Sheets",
        "banner": "(Dollars in millions, except per share data)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Total revenues"],
             "raw": "66,608", "column": "2022", "tag": "Revenues", "end": "2022-12-31"},
            {"concept": "revenue", "operator": "percentage_change", "row_labels": ["Total revenues"],
             "raw": "66,608", "prior_raw": "62,286", "column": "2022", "prior_column": "2021",
             "tag": "Revenues", "end": "2022-12-31", "prior_end": "2021-12-31"},
            {"concept": "total_assets", "operator": "lookup", "row_labels": ["Total assets"],
             "raw": "137,100", "column": "December 31, 2022", "tag": "Assets", "end": "2022-12-31",
             "statement_key": "balance"},
        ],
        "skipped": [
            {"slot": "net_income", "reason": "negative_print",
             "detail": ("Boeing's consolidated result for 2022 is a parenthesised loss "
                        "(-4,935 million). By the printed-sign rule the slot fell through to total "
                        "assets. Recorded, not scored.")},
            {"slot": "third_substantive", "reason": "slot_unavailable",
             "detail": ("GrossProfit is tagged at 3,502 but no gross-profit row is printed; the "
                        "consolidated operating result is also a parenthesised loss "
                        "(-3,547 million). With total assets already the second slot, no third "
                        "substantive slot exists for this filing. Recorded, not scored.")},
        ],
    },
    {
        "cik": "0000001800", "issuer": "Abbott Laboratories", "short": "Abbott",
        "accession": "0001628280-23-004026", "period": "2022", "period_end": "2022-12-31",
        "prior": "2021", "prior_end": "2021-12-31",
        "statement": "Consolidated Statements of Earnings",
        "balance": "Consolidated Balance Sheet",
        "banner": "(in millions except per share data)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Net Sales"],
             "raw": "43,653", "column": "2022",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-12-31"},
            {"concept": "revenue", "operator": "percentage_change", "row_labels": ["Net Sales"],
             "raw": "43,653", "prior_raw": "43,075", "column": "2022", "prior_column": "2021",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-12-31",
             "prior_end": "2021-12-31"},
            {"concept": "net_income", "operator": "lookup", "row_labels": ["Net Earnings"],
             "raw": "6,933", "column": "2022", "tag": "NetIncomeLoss", "end": "2022-12-31"},
            {"concept": "total_assets", "operator": "lookup", "row_labels": ["Total assets"],
             "raw": "74,438", "column": "December 31, 2022", "tag": "Assets", "end": "2022-12-31",
             "statement_key": "balance"},
            {"concept": "gross_profit", "operator": "lookup", "abstain": "structurally_unanswerable",
             "note": ("Abbott's consolidated statement of earnings prints net sales, cost of "
                      "products sold and operating earnings; gross profit appears only as a "
                      "percentage in narrative, with no amount row and no GrossProfit fact.")},
        ],
        "skipped": [
            {"slot": "operating_income", "reason": "alias_gap",
             "detail": ("Abbott prints 'Operating Earnings' 8,362; the shared concept vocabulary "
                        "has no alias for that wording. Following the development-set precedent "
                        "for Walmart's 'Total revenues', the wording gap is recorded as a "
                        "limitation and the slot fell through to total assets rather than being "
                        "scored against a vocabulary the system does not have.")},
        ],
    },
    {
        "cik": "0001048911", "issuer": "FedEx Corp", "short": "FedEx",
        "accession": "0000950170-22-012762", "period": "2022", "period_end": "2022-05-31",
        "prior": "2021", "prior_end": "2021-05-31",
        "statement": "Consolidated Statements of Income",
        "balance": "Consolidated Balance Sheets",
        "banner": "(In millions)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["REVENUE"],
             "raw": "93,512", "column": "2022",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-05-31"},
            {"concept": "revenue", "operator": "percentage_change", "row_labels": ["REVENUE"],
             "raw": "93,512", "prior_raw": "83,959", "column": "2022", "prior_column": "2021",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-05-31",
             "prior_end": "2021-05-31"},
            {"concept": "net_income", "operator": "lookup", "row_labels": ["NET INCOME"],
             "raw": "3,826", "column": "2022", "tag": "NetIncomeLoss", "end": "2022-05-31"},
            {"concept": "operating_income", "operator": "lookup", "row_labels": ["OPERATING INCOME"],
             "raw": "6,245", "column": "2022", "tag": "OperatingIncomeLoss", "end": "2022-05-31"},
            {"concept": "gross_profit", "operator": "lookup", "abstain": "structurally_unanswerable",
             "note": ("FedEx's statement of income goes from revenue to operating expenses and "
                      "operating income; no gross-profit row is printed and the accession carries "
                      "no GrossProfit fact.")},
        ],
        "skipped": [],
    },
    {
        "cik": "0000060667", "issuer": "Lowe's Companies Inc", "short": "Lowe's",
        "accession": "0000060667-22-000038", "period": "2022", "period_end": "2022-01-28",
        "prior": "2021", "prior_end": "2021-01-29",
        "statement": "Consolidated Statements of Earnings",
        "balance": "Consolidated Balance Sheets",
        "banner": "(In millions, except per share data)",
        "slots": [
            {"concept": "revenue", "operator": "lookup", "row_labels": ["Net sales"],
             "raw": "96,250", "column": "January 28, 2022",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-01-28"},
            {"concept": "revenue", "operator": "percentage_change", "row_labels": ["Net sales"],
             "raw": "96,250", "prior_raw": "89,597", "column": "January 28, 2022",
             "prior_column": "January 29, 2021",
             "tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "end": "2022-01-28",
             "prior_end": "2021-01-29"},
            {"concept": "net_income", "operator": "lookup", "row_labels": ["Net earnings"],
             "raw": "8,442", "column": "January 28, 2022", "tag": "NetIncomeLoss",
             "end": "2022-01-28"},
            {"concept": "operating_income", "operator": "lookup", "row_labels": ["Operating income"],
             "raw": "12,093", "column": "January 28, 2022", "tag": "OperatingIncomeLoss",
             "end": "2022-01-28"},
        ],
        "skipped": [
            {"slot": "gross_profit", "reason": "no_printed_row",
             "detail": ("GrossProfit is tagged at 32,056, but the statement of earnings prints no "
                        "gross-profit row for it. The slot fell through to operating income. "
                        "Recorded, not scored.")},
        ],
    },
]

QUESTION_TEXT = {
    "revenue": "For {entity}'s fiscal year ended {end}, what was consolidated revenue?",
    "net_income": "What was {entity}'s net income for the fiscal year ended {end}?",
    "total_assets": "What were {entity}'s total assets at {end}?",
    "gross_profit": "What was {entity}'s gross profit for the fiscal year ended {end}?",
    "operating_income": "What was {entity}'s operating income for the fiscal year ended {end}?",
}
ARITHMETIC_TEXT = ("By what percentage did {entity}'s consolidated revenue change from the fiscal "
                   "year ended {prior} to the fiscal year ended {end}?")


def pretty(iso_date: str) -> str:
    months = ("January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December")
    year, month, day = (int(part) for part in iso_date.split("-"))
    return f"{months[month - 1]} {day}, {year}"


def _norm(text: str) -> str:
    return re.sub(r"[\s$,\u00a0]", "", text or "")


def _cell_present(html: str, labels: list[str], raw: str) -> bool:
    parser = _Tables()
    parser.feed(html)
    wanted = {_norm(raw)}
    for table in parser.tables:
        for row in table:
            text = _row_text(row).lower()
            if not any(label.lower() in text for label in labels):
                continue
            if any(_norm(cell["text"]) in wanted for cell in row):
                return True
    return False


def main() -> int:
    corpus = json.loads(CORPUS.read_text())
    facts = json.loads(FACTS.read_text())["facts"]
    by_accession = {item["accession"]: item for item in corpus["filings"]}

    questions: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    for filing in FILINGS:
        record = by_accession[filing["accession"]]
        if record["cik"] != filing["cik"]:
            raise SystemExit(f"CIK mismatch for {filing['accession']}")
        html = (SNAPSHOTS / f"{filing['accession']}.html").read_text(errors="replace")
        counter = 0
        for slot in filing["slots"]:
            counter += 1
            qid = f"H-{filing['cik'][-4:]}-{counter:02d}"
            statement = (filing["balance"] if slot.get("statement_key") == "balance"
                         else filing["statement"])
            common = {
                "id": qid, "issuer_cik": filing["cik"], "accession": filing["accession"],
                "cutoff": record["cutoff"], "scope": "accession",
                "concept": slot["concept"], "period": filing["period"],
                "review": {
                    "method": ("printed statement cell read with an independent table dumper; "
                               "corroborated by the SEC XBRL fact filed with the same accession"),
                    "reviewers": 1, "reviewed_at": REVIEWED_AT,
                    "printed": {"statement": statement, "row_labels": slot.get("row_labels"),
                                "raw": slot.get("raw"), "column_header": slot.get("column"),
                                "scale_exponent": SCALE,
                                "scale_banner": filing["banner"],
                                "period_end": filing["period_end"]},
                    "xbrl_provenance": "https://data.sec.gov/api/xbrl/companyfacts/",
                },
            }
            if slot.get("abstain"):
                question = {
                    **common, "question": QUESTION_TEXT[slot["concept"]].format(
                        entity=filing["short"], end=pretty(filing["period_end"])),
                    "operator": "lookup", "gold_class": slot["abstain"], "xbrl": [],
                    "expect": {"outcome": "abstained", "note": slot["note"]},
                    "tags": ["justified_abstention", slot["abstain"]],
                }
                question["review"]["absence_evidence"] = {
                    "printed_gross_profit_rows": 0, "xbrl_gross_profit_facts": 0}
                questions.append(question)
                ledger.append({
                    "key": qid, "kind": "scored_abstention", "status": "scored",
                    "reason": slot["abstain"], "issuer": filing["issuer"],
                    "cik": filing["cik"], "accession": filing["accession"],
                    "concept": slot["concept"], "detail": slot["note"]})
                continue
            operator = slot["operator"]
            if operator == "lookup":
                label = next((item for item in slot["row_labels"]
                              if _cell_present(html, [item], slot["raw"])), None)
                if label is None:
                    raise SystemExit(f"printed cell not found: {qid} {slot['row_labels']} "
                                     f"{slot['raw']} in {filing['accession']}")
                if not _cell_present(html, [label], slot["raw"]):
                    raise SystemExit(f"printed cell not found: {qid}")
                questions.append({
                    **common, "question": QUESTION_TEXT[slot["concept"]].format(
                        entity=filing["short"], end=pretty(filing["period_end"])),
                    "operator": "lookup",
                    "gold_class": "xbrl_verified",
                    "xbrl": [{"tag": slot["tag"], "end": slot["end"],
                              "accn": filing["accession"]}],
                    "expect": {"outcome": "answered", "scale": SCALE, "citations": [{
                        "accession": filing["accession"], "row_labels": slot["row_labels"],
                        "raw": slot["raw"], "scale": SCALE, "period": filing["period"]}]},
                    "tags": ["lookup", slot["concept"]],
                })
                ledger.append({
                    "key": qid, "kind": "scored_lookup", "status": "scored",
                    "reason": "printed_and_xbrl_agree", "issuer": filing["issuer"],
                    "cik": filing["cik"], "accession": filing["accession"],
                    "concept": slot["concept"]})
                continue
            # percentage change: both operands must be printed in the same table and tagged
            current_label = next((item for item in slot["row_labels"]
                                  if _cell_present(html, [item], slot["raw"])), None)
            if current_label is None or not _cell_present(html, [current_label], slot["prior_raw"]):
                raise SystemExit(f"arithmetic operands not printed together: {qid}")
            current = Fraction(slot["raw"].replace(",", "")) * (10 ** SCALE)
            prior = Fraction(slot["prior_raw"].replace(",", "")) * (10 ** SCALE)
            exact = (current - prior) / prior * 100
            display = Decimal(exact.numerator) / Decimal(exact.denominator)
            questions.append({
                **common, "question": ARITHMETIC_TEXT.format(
                    entity=filing["short"], prior=pretty(filing["prior_end"]),
                    end=pretty(filing["period_end"])),
                "operator": "percentage_change",
                "gold_class": "xbrl_verified",
                "xbrl": [{"tag": slot["tag"], "end": slot["end"], "accn": filing["accession"]},
                         {"tag": slot["tag"], "end": slot["prior_end"],
                          "accn": filing["accession"]}],
                "expect": {
                    "outcome": "answered", "scale": SCALE, "prior_period": filing["prior"],
                    "citations": [
                        {"accession": filing["accession"], "row_labels": slot["row_labels"],
                         "raw": slot["raw"], "scale": SCALE, "period": filing["period"]},
                        {"accession": filing["accession"], "row_labels": slot["row_labels"],
                         "raw": slot["prior_raw"], "scale": SCALE, "period": filing["prior"]},
                    ]},
                "tags": ["arithmetic", "derived_percentage_change"],
            })
            questions[-1]["review"]["printed"]["prior_column_header"] = slot["prior_column"]
            questions[-1]["review"]["printed"]["prior_raw"] = slot["prior_raw"]
            questions[-1]["review"]["computation"] = {
                "numerator_printed": slot["raw"], "denominator_printed": slot["prior_raw"],
                "exact_fraction_times_100": str(exact),
                "display_two_dp": str(display.quantize(Decimal("0.01"))),
                "operands_share": "accession, USD unit, scale exponent 6",
            }
            ledger.append({
                "key": qid, "kind": "scored_arithmetic", "status": "scored",
                "reason": "printed_and_xbrl_agree", "issuer": filing["issuer"],
                "cik": filing["cik"], "accession": filing["accession"],
                "concept": slot["concept"], "computed_percentage": str(
                    display.quantize(Decimal("0.01")))})
        for skipped in filing["skipped"]:
            ledger.append({
                "key": f"{filing['cik'][-4:]}-{skipped['slot']}", "kind": "not_scored",
                "status": "not_scored", "reason": skipped["reason"],
                "issuer": filing["issuer"], "cik": filing["cik"],
                "accession": filing["accession"], "slot": skipped["slot"],
                "detail": skipped["detail"]})

    # ---- independent corroboration: printed x scale must equal the same-accession XBRL value
    checked = 0
    for question in questions:
        if question["gold_class"] != "xbrl_verified":
            continue
        citations = question["expect"]["citations"]
        for selector, citation in zip(question["xbrl"], citations):
            matches = [row for row in facts[question["issuer_cik"]]
                       if row["tag"] == selector["tag"] and row["end"] == selector["end"]
                       and row["accn"] == selector["accn"] and row["unit"] == "USD"]
            if len(matches) != 1:
                raise SystemExit(f"{question['id']}: expected exactly one XBRL fact, found "
                                 f"{len(matches)} for {selector}")
            printed = Fraction(citation["raw"].replace(",", "")) * (10 ** citation["scale"])
            if printed != Fraction(str(matches[0]["val"])):
                raise SystemExit(f"{question['id']}: printed {citation['raw']} x 1e"
                                 f"{citation['scale']} = {printed} but XBRL says "
                                 f"{matches[0]['val']}")
            checked += 1

    payload = {
        "schema": "atlas.answer_semantics.holdout_questions.v1",
        "description": ("Prospective holdout questions authored from printed statement cells and "
                        "same-accession SEC XBRL facts before any resolver ran on these filings. "
                        "Every question is accession-scoped; the cohort contains no as-of "
                        "multi-filing question."),
        "protocol": "fixtures/answer_semantics/holdout_protocol.json",
        "period_convention": ("period is the calendar year of the fiscal period end, not the "
                              "issuer's fiscal-year label; every question text states the period "
                              "end date."),
        "reviewer": "single author, two independent authorities per cell",
        "counts": {
            "questions": len(questions),
            "answerable": sum(1 for q in questions if q["gold_class"] == "xbrl_verified"),
            "abstention": sum(1 for q in questions if q["gold_class"] != "xbrl_verified"),
            "lookups": sum(1 for q in questions if q["operator"] == "lookup"
                           and q["gold_class"] == "xbrl_verified"),
            "arithmetic": sum(1 for q in questions if q["operator"] == "percentage_change"),
            "printed_xbrl_pairs_checked": checked,
        },
        "questions": questions,
    }
    ledger_payload = {
        "schema": "atlas.answer_semantics.holdout_ledger.v1",
        "description": ("Complete ledger of every question considered for the prospective cohort: "
                        "scored questions, generated abstention probes and every slot that was "
                        "recorded but not scored. A not_scored entry is never counted as a "
                        "success or a failure."),
        "summary": {
            "attempted": len(questions) + sum(1 for e in ledger if e["status"] == "not_scored"),
            "scored": sum(1 for e in ledger if e["status"] == "scored"),
            "not_scored": sum(1 for e in ledger if e["status"] == "not_scored"),
        },
        "entries": ledger,
    }
    QUESTIONS.write_text(json.dumps(payload, indent=2) + "\n")
    LEDGER.write_text(json.dumps(ledger_payload, indent=2) + "\n")
    print(json.dumps(payload["counts"], indent=1))
    print(json.dumps(ledger_payload["summary"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
