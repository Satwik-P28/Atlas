"""FinanceBench adapter: explicit issuer identity, no fuzzy matching.

The dataset names companies in prose ("3M", "JPMorgan"). Mapping those to SEC CIKs by string
similarity produced Amazon→AAON and Verizon→Veritone in testing, which would silently attach
questions to the wrong company. The mapping below is explicit, and every entry is checked against
the SEC's own issuer name at ingestion time; an unverified company is excluded rather than guessed.

Dataset: PatronusAI/financebench, OPEN_SOURCE sample, license CC-BY-NC-4.0. Questions, answers and
source documents stay outside the repository; only derived metrics are committed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATASET_ID = "PatronusAI/financebench"
DATASET_LICENSE = "cc-by-nc-4.0"
DATASET_SUBSET = "OPEN_SOURCE"
#: Rights position: evaluation only. No question text, answer or source document is redistributed.
USAGE = "evaluation_only_no_redistribution"

#: company -> (CIK, tokens that must appear in the SEC issuer name)
ISSUERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "3M": ("0000066740", ("3m",)),
    "AES Corporation": ("0000874761", ("aes",)),
    "AMD": ("0000002488", ("advanced", "micro")),
    "Activision Blizzard": ("0000718877", ("activision",)),
    "Adobe": ("0000796343", ("adobe",)),
    "Amazon": ("0001018724", ("amazon",)),
    "Amcor": ("0001748790", ("amcor",)),
    "American Express": ("0000004962", ("american", "express")),
    "American Water Works": ("0001410636", ("american", "water")),
    "Best Buy": ("0000764478", ("best", "buy")),
    "Block": ("0001512673", ("block",)),
    "Boeing": ("0000012927", ("boeing",)),
    "CVS Health": ("0000064803", ("cvs",)),
    "Coca-Cola": ("0000021344", ("coca", "cola")),
    "Corning": ("0000024741", ("corning",)),
    "Costco": ("0000909832", ("costco",)),
    "Foot Locker": ("0000850209", ("foot", "locker")),
    "General Mills": ("0000040704", ("general", "mills")),
    "JPMorgan": ("0000019617", ("jpmorgan",)),
    "Johnson & Johnson": ("0000200406", ("johnson",)),
    "Kraft Heinz": ("0001637459", ("kraft", "heinz")),
    "Lockheed Martin": ("0000936468", ("lockheed",)),
    "MGM Resorts": ("0000789570", ("mgm",)),
    "Microsoft": ("0000789019", ("microsoft",)),
    "Netflix": ("0001065280", ("netflix",)),
    "Nike": ("0000320187", ("nike",)),
    "Paypal": ("0001633917", ("paypal",)),
    "PepsiCo": ("0000077476", ("pepsico",)),
    "Pfizer": ("0000078003", ("pfizer",)),
    "Ulta Beauty": ("0001403568", ("ulta",)),
    "Verizon": ("0000732712", ("verizon",)),
    "Walmart": ("0000104169", ("walmart",)),
}


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text())


def open_source_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("dataset_subset_label") == DATASET_SUBSET]


def cik_for(company: str) -> str | None:
    entry = ISSUERS.get(company)
    return entry[0] if entry else None


def manifest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    companies = sorted({row["company"] for row in rows})
    return {
        "dataset": DATASET_ID,
        "license": DATASET_LICENSE,
        "subset": DATASET_SUBSET,
        "usage": USAGE,
        "rows": len(rows),
        "companies": len(companies),
        "periods": sorted({str(row["doc_period"]) for row in rows}),
        "doc_types": sorted({str(row["doc_type"]) for row in rows}),
        "issuer_map_verified_by": "sec submissions issuer name",
    }


__all__ = ["ISSUERS", "DATASET_ID", "DATASET_LICENSE", "load_rows", "open_source_rows",
           "cik_for", "manifest"]
