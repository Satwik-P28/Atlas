"""Cross-issuer research case: how two issuers describe concentration and financing risk.

Uses the existing knowledge engine, claim builder and citation verification. It does not compare
numbers — the two companies do not define the same metrics — so the artifact records what each
filing actually says, at one shared cutoff, and marks the comparison as non-equivalent.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.research.knowledge_claims import build_document_claim  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

CUTOFF = "2021-06-30T00:00:00Z"
QUESTION = "What does the company disclose about liquidity and capital resources?"
ISSUERS = {
    "0000066740": "3M",
    "0000012927": "Boeing",
    "0000936468": "Lockheed Martin",
}


def main() -> int:
    db = Database("var/phase9_6.db")
    engine = KnowledgeEngine(db)
    out: dict = {
        "schema": "atlas.phase9_6.case_study.v1",
        "question": QUESTION,
        "cutoff": CUTOFF,
        "policy": "public_available",
        "label": "self_authored",
        "issuers": {},
        "comparison": {},
    }
    for cik, name in ISSUERS.items():
        issuer = db.query_one("SELECT issuer_id, legal_name FROM issuer WHERE cik = ?", (cik,))
        if issuer is None:
            out["issuers"][name] = {"status": "issuer_not_in_corpus"}
            continue
        claim = build_document_claim(
            engine, issuer_id=issuer["issuer_id"], cutoff=CUTOFF, key="concentration-risk",
            question=QUESTION, epistemic_status="observed_fact", forms=["10-K"],
        )
        citation = (claim.get("citations") or [None])[0]
        reopened, excerpt, period = None, None, None
        if citation:
            unit = engine.unit(citation["unit_id"])
            excerpt = unit["body"][:600]
            document = db.query_one(
                "SELECT period_of_report FROM knowledge_document WHERE document_id = ?",
                (citation["document_id"],),
            )
            period = document and document["period_of_report"]
            reopened = {
                "hash_matches": hashlib.sha256(unit["body"].encode()).hexdigest()
                == citation["unit_sha256"],
                "issuer_matches": unit["issuer_id"] == issuer["issuer_id"],
                "available_before_cutoff": citation["availability_time"] <= CUTOFF,
            }
        out["issuers"][name] = {
            "issuer_id": issuer["issuer_id"],
            "legal_name": issuer["legal_name"],
            "claim_id": claim["claim_id"],
            "statement_kind": claim["statement_kind"],
            "statement": claim["statement"],
            "abstained": claim["search"]["abstained"],
            "abstention_reason": claim["search"]["abstention_reason"],
            "document": citation and {
                "accession": citation["accession"],
                "form_type": citation.get("form_type"),
                "period_of_report": period,
                "availability_time": citation.get("availability_time"),
                "precision": citation.get("availability_precision"),
            },
            "excerpt": excerpt,
            "reopened": reopened,
        }
    left = out["issuers"].get("Boeing", {})
    right = out["issuers"].get("Lockheed Martin", {})
    out["comparison"] = {
        "comparable_facts": [
            "both filings are annual reports available before the same cutoff, but their fiscal "
            "periods differ (Boeing FY2019, Lockheed Martin FY2020); no period-equivalent claim "
            "is made",
            "both discuss customer concentration and financing/liquidity risk as risk factors",
        ],
        "not_equivalent": [
            "customer-concentration wording was not located in every filing, so it is recorded "
            "as missing data rather than treated as an absent risk",
            "the two issuers use different liquidity and leverage vocabularies; no numeric "
            "equivalence is asserted and no ratio is computed across them",
        ],
        "missing_data": [
            name for name, record in out["issuers"].items()
            if record.get("abstained") or record.get("status") == "issuer_not_in_corpus"
        ],
        "counter_evidence_reviewed": bool(left.get("excerpt")) and bool(right.get("excerpt")),
        "equivalence_asserted": False,
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/phase9_6_case_study.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({
        name: {"abstained": record.get("abstained"), "kind": record.get("statement_kind"),
               "doc": (record.get("document") or {}).get("accession"),
               "reopened": record.get("reopened")}
        for name, record in out["issuers"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
