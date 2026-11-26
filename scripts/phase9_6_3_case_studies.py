"""Phase 9.6.3 case studies: three issuers, verification packets, honest failures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research.financial_answers import FinancialAnswerEngine
from atlas.research.financial_concepts import ConceptResolver
from atlas.research.knowledge import KnowledgeEngine
from atlas.storage.db import Database

CASES = [
    ("operating", "COCA COLA CO", "2023-06-30T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2022"}),
    ("operating", "COCA COLA CO", "2023-06-30T00:00:00Z", "lookup",
     {"concept": "net_income", "period": "2022"}),
    ("operating", "COCA COLA CO", "2023-06-30T00:00:00Z", "percentage_change",
     {"metric": "revenue", "current_period": "2022", "prior_period": "2021"}),
    ("operating", "COCA COLA CO", "2023-06-30T00:00:00Z", "margin",
     {"numerator": "operating income", "revenue": "revenue", "period": "2022"}),
    ("operating", "COCA COLA CO", "2023-06-30T00:00:00Z", "ratio",
     {"numerator": "total assets", "denominator": "revenue", "period": "2022"}),
    ("bank", "JPMORGAN CHASE & CO", "2024-01-01T00:00:00Z", "lookup",
     {"concept": "total_assets", "period": "2022"}),
    ("bank", "JPMORGAN CHASE & CO", "2024-01-01T00:00:00Z", "lookup",
     {"concept": "net_income", "period": "2022"}),
    ("bank", "JPMORGAN CHASE & CO", "2024-01-01T00:00:00Z", "margin",
     {"numerator": "net income", "revenue": "total net revenue", "period": "2022"}),
    ("bank", "JPMORGAN CHASE & CO", "2024-01-01T00:00:00Z", "lookup",
     {"concept": "gross_profit", "period": "2022"}),
    ("segment", "3M CO", "2024-01-01T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2022"}),
    ("segment", "3M CO", "2024-01-01T00:00:00Z", "percentage_change",
     {"metric": "revenue", "current_period": "2022", "prior_period": "2021"}),
    ("segment", "3M CO", "2024-01-01T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2018"}),
]


def issuer_id(db: Database, name: str) -> str:
    row = db.query_one("SELECT issuer_id FROM issuer WHERE legal_name = ?", (name,))
    if row is None:
        raise SystemExit(f"issuer not found: {name}")
    return row["issuer_id"]


def main() -> int:
    db = Database("var/phase9_6.db")
    knowledge = KnowledgeEngine(db)
    answers = FinancialAnswerEngine(knowledge)
    resolver = ConceptResolver(knowledge)
    packets = []
    for family, name, cutoff, operator, kwargs in CASES:
        iid = issuer_id(db, name)
        packet: dict = {"family": family, "issuer": name, "cutoff": cutoff,
                        "operator": operator, "request": kwargs}
        if operator == "lookup":
            resolution = resolver.resolve(iid, kwargs["concept"], kwargs["period"], cutoff)
            packet["resolution"] = resolution.as_dict()
            if resolution.status != "resolved" or resolution.cell is None:
                packet["outcome"] = "abstained"
                packet["reason"] = f"concept_resolution:{resolution.status}"
            else:
                result = answers.lookup(iid, cutoff, metric=resolution.cell.row_label,
                                        period=kwargs["period"])
                packet.update(result)
                packet["research_task"] = (f"What was {name}'s {kwargs['concept'].replace('_', ' ')} "
                                      f"in FY{kwargs['period']}?")
        else:
            result = getattr(answers, operator)(iid, cutoff, **kwargs)
            packet.update(result)
            packet["research_task"] = f"{operator.replace('_', ' ')} for {name} ({kwargs})"
        packets.append(packet)
    payload = {
        "schema": "atlas.phase9_6_3.case_studies.v1",
        "version": "9.6.3",
        "research_tasks": len(packets),
        "answered": sum(1 for p in packets if p.get("outcome") == "answered"),
        "abstained": sum(1 for p in packets if p.get("outcome") != "answered"),
        "packets": packets,
        "limitations": [
            "Cutoffs restrict evidence to filings available on that date.",
            "The bank case intentionally includes a gross-profit lookup; the refusal is a finding.",
            "Scale is reported as printed; no hidden unit conversion is applied.",
        ],
    }
    Path("artifacts/phase9_6_3_case_studies.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    for packet in packets:
        print(packet["family"], packet["issuer"], packet["operator"],
              packet.get("outcome"), packet.get("value"), packet.get("reason"),
              (packet.get("inputs") or [{}])[0].get("row_label") if packet.get("inputs") else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
