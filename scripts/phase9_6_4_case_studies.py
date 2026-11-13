"""Phase 9.6.4 case studies: resolver bindings carried into FEC, no second corpus search."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research.financial_answers import FinancialAnswerEngine
from atlas.research.financial_concepts import ConceptResolver, bind
from atlas.research.knowledge import KnowledgeEngine
from atlas.storage.db import Database

CASES = [
    ("operating", "COCA COLA CO", "2023-06-30T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2022"}),
    ("operating", "COCA COLA CO", "2023-06-30T00:00:00Z", "lookup",
     {"concept": "net_income", "period": "2022"}),
    ("operating", "COCA COLA CO", "2023-06-30T00:00:00Z", "percentage_change",
     {"concept": "revenue", "current_period": "2022", "prior_period": "2021"}),
    ("operating", "COCA COLA CO", "2023-06-30T00:00:00Z", "margin",
     {"numerator": "operating_income", "concept": "revenue", "period": "2022"}),
    ("operating", "COCA COLA CO", "2023-06-30T00:00:00Z", "ratio",
     {"numerator": "total_assets", "concept": "revenue", "period": "2022"}),
    ("bank", "JPMORGAN CHASE & CO", "2024-01-01T00:00:00Z", "lookup",
     {"concept": "total_assets", "period": "2022"}),
    ("bank", "JPMORGAN CHASE & CO", "2024-01-01T00:00:00Z", "lookup",
     {"concept": "net_income", "period": "2022"}),
    ("bank", "JPMORGAN CHASE & CO", "2024-01-01T00:00:00Z", "ratio",
     {"numerator": "net_income", "concept": "total_assets", "period": "2022"}),
    ("bank", "JPMORGAN CHASE & CO", "2024-01-01T00:00:00Z", "lookup",
     {"concept": "gross_profit", "period": "2022"}),
    ("segment", "3M CO", "2024-01-01T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2022"}),
    ("segment", "3M CO", "2024-01-01T00:00:00Z", "percentage_change",
     {"concept": "revenue", "current_period": "2022", "prior_period": "2021"}),
    ("segment", "3M CO", "2024-01-01T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2018"}),
    ("cutoff", "3M CO", "2017-01-01T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2022"}),
]


def issuer_id(db: Database, name: str) -> str:
    row = db.query_one("SELECT issuer_id FROM issuer WHERE legal_name = ?", (name,))
    if row is None:
        raise SystemExit(f"issuer not found: {name}")
    return row["issuer_id"]


def look(resolver: ConceptResolver, iid: str, concept: str, period: str, cutoff: str):
    resolution = resolver.resolve(iid, concept, period, cutoff)
    return resolution, bind(resolution, iid, concept)


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
            resolution, binding = look(resolver, iid, kwargs["concept"],
                                       kwargs["period"], cutoff)
            packet["resolution"] = resolution.as_dict()
            if binding is None:
                packet["outcome"] = "abstained"
                packet["reason"] = f"concept_resolution:{resolution.status}"
            else:
                packet["binding"] = binding.__dict__ if hasattr(binding, "__dict__") else {
                    field: getattr(binding, field) for field in binding.__slots__}
                packet.update(answers.lookup_bound(binding, cutoff))
        elif operator == "percentage_change":
            current_res, current_bind = look(resolver, iid, kwargs["concept"],
                                             kwargs["current_period"], cutoff)
            prior_res, prior_bind = look(resolver, iid, kwargs["concept"],
                                         kwargs["prior_period"], cutoff)
            packet["resolution"] = {"current": current_res.as_dict(),
                                    "prior": prior_res.as_dict()}
            if current_bind is None or prior_bind is None:
                packet["outcome"] = "abstained"
                packet["reason"] = "concept_resolution:" + ",".join(
                    f"{period}={res.status}" for period, res in
                    ((kwargs["current_period"], current_res), (kwargs["prior_period"], prior_res)))
            else:
                packet.update(answers.percentage_change_bound(
                    current_bind, prior_bind, cutoff,
                    metric=f"{kwargs['concept']} {kwargs['current_period']} vs {kwargs['prior_period']}"))
        else:
            numerator_res, numerator_bind = look(resolver, iid, kwargs["numerator"],
                                                 kwargs["period"], cutoff)
            base_res, base_bind = look(resolver, iid, kwargs["concept"],
                                       kwargs["period"], cutoff)
            packet["resolution"] = {"numerator": numerator_res.as_dict(),
                                    "base": base_res.as_dict()}
            if numerator_bind is None or base_bind is None:
                missing = [res.status for res in (numerator_res, base_res) if res.status != "resolved"]
                packet["outcome"] = "abstained"
                packet["reason"] = "concept_resolution:" + ",".join(missing)
            elif operator == "margin":
                packet.update(answers.margin_bound(numerator_bind, base_bind, cutoff))
            else:
                packet.update(answers.ratio_bound(numerator_bind, base_bind, cutoff))
        packet["research_task"] = f"{name}: {operator} {kwargs}"
        packets.append(packet)
    payload = {
        "schema": "atlas.phase9_6_4.case_studies.v1",
        "version": "9.6.4",
        "research_tasks": len(packets),
        "answered": sum(1 for p in packets if p.get("outcome") == "answered"),
        "abstained": sum(1 for p in packets if p.get("outcome") != "answered"),
        "packets": packets,
        "limitations": [
            "Cutoffs restrict evidence to filings available on that date.",
            "The bank case intentionally includes a gross-profit lookup; the refusal is a finding.",
            "Values are reported in the unit and scale printed in the filing.",
        ],
    }
    Path("artifacts/phase9_6_4_case_studies.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    for packet in packets:
        print(packet["family"], packet["issuer"], packet["operator"],
              packet.get("outcome"), packet.get("value"), packet.get("reason"),
              ((packet.get("inputs") or [{}])[0] or {}).get("row_label", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
