"""Reproducible FOCUS demonstration: real filings → bound answer → certificate → verify → refuse.

Exit codes:
  0 success
  1 required demonstration step failed
  2 environment / dependency / corpus unavailable
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research.certificate import build_certificate, verify_certificate_payload  # noqa: E402
from atlas.research.financial_answers import FinancialAnswerEngine  # noqa: E402
from atlas.research.financial_concepts import ConceptResolver, bind  # noqa: E402
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

DB_PATH = Path(os.environ.get("ATLAS_FOCUS_DB", "var/focus_demo.db"))
OUT_DIR = Path(os.environ.get("ATLAS_FOCUS_OUT", "artifacts/focus_demo"))


def _require_user_agent() -> None:
    if not os.environ.get("ATLAS_SEC_USER_AGENT", "").strip():
        raise SystemExit(
            "2: set ATLAS_SEC_USER_AGENT to a declared identity with a working contact address")


def _ensure_corpus() -> None:
    if DB_PATH.exists():
        return
    _require_user_agent()
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "focus_build_corpus.py"),
         "--db", str(DB_PATH)],
        cwd=ROOT, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"2: focus corpus build failed with exit {completed.returncode}")


def _issuer_id(db: Database, name: str) -> str:
    row = db.query_one("SELECT issuer_id FROM issuer WHERE legal_name = ?", (name,))
    if row is None:
        raise SystemExit(f"1: issuer not found in focus corpus: {name}")
    return row["issuer_id"]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {"schema": "atlas.focus.demo.v1", "steps": []}

    # 1. Dependencies
    try:
        import numpy  # noqa: F401
        from atlas.fec import compile_model  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"dependency check failed: {exc}", file=sys.stderr)
        return 2
    report["steps"].append({"step": "dependencies", "status": "ok"})

    # 2–3. Corpus
    try:
        _ensure_corpus()
    except SystemExit as exc:
        message = str(exc)
        code = 2 if message.startswith("2:") else 1
        print(message, file=sys.stderr)
        return code
    if not DB_PATH.exists():
        return 2
    report["steps"].append({"step": "corpus", "status": "ok", "database": str(DB_PATH)})

    db = Database(str(DB_PATH))
    knowledge = KnowledgeEngine(db)
    answers = FinancialAnswerEngine(knowledge)
    resolver = ConceptResolver(knowledge)

    issuer = _issuer_id(db, "3M CO")
    cutoff = "2024-01-01T00:00:00Z"
    question = "What were 3M consolidated net sales for fiscal year 2022?"

    # 4–6. Resolve, bind, FEC answer
    resolution = resolver.resolve(issuer, "revenue", "2022", cutoff)
    binding = bind(resolution, issuer, "revenue")
    if binding is None or resolution.status != "resolved":
        report["steps"].append({"step": "resolve", "status": "failed",
                                "resolution": resolution.as_dict()})
        (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 1
    answer = answers.lookup_bound(binding, cutoff)
    if answer.get("outcome") != "answered":
        report["steps"].append({"step": "answer", "status": "failed", "answer": answer})
        (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 1
    if binding.scale != 6:
        report["steps"].append({
            "step": "scale_check", "status": "failed",
            "scale": binding.scale, "raw": binding.raw,
            "detail": "3M FY2022 net sales must carry USD millions (scale 6)",
        })
        (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 1
    report["steps"].append({
        "step": "answer", "status": "ok",
        "value": answer["value"], "economic_amount": answer.get("economic_amount"),
        "scale": binding.scale, "raw": binding.raw, "accession": binding.accession,
        "statement_family": binding.statement_family, "entity_scope": binding.entity_scope,
    })

    # 7. Certificate
    certificate = build_certificate(
        research_question=question, answer=answer, bindings=[binding], cutoff=cutoff,
        normalized_requirement={"operator": "lookup", "concept": "revenue", "period": "2022",
                                "issuer": "3M CO"},
    )
    cert_path = OUT_DIR / "certificate.json"
    cert_path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    report["steps"].append({
        "step": "certificate", "status": "ok",
        "path": str(cert_path),
        "fingerprint": certificate["certificate_fingerprint"],
    })

    # 8. Independent verification (module + CLI)
    trusted = {
        binding.accession: {
            "sha256": binding.source_table_sha256,
            "availability_time": binding.availability_time,
            "body_present": True,
        }
    }
    verified = verify_certificate_payload(certificate, trusted_sources=trusted)
    if verified["status"] != "valid":
        report["steps"].append({"step": "verify", "status": "failed", "result": verified})
        (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 1
    cli = subprocess.run(
        [sys.executable, "-m", "atlas", "verify-certificate", str(cert_path)],
        cwd=ROOT, capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    if cli.returncode != 0:
        report["steps"].append({"step": "verify_cli", "status": "failed",
                                "stdout": cli.stdout[-1000:], "stderr": cli.stderr[-1000:]})
        (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 1
    report["steps"].append({"step": "verify", "status": "ok", "result": verified})

    # 9. Adversarial tamper
    tampered = json.loads(json.dumps(certificate))
    tampered["result"]["value"] = "99999.00"
    tamper_check = verify_certificate_payload(tampered, trusted_sources=trusted)
    if tamper_check["status"] == "valid":
        report["steps"].append({"step": "adversarial_tamper", "status": "failed",
                                "detail": "tampered certificate incorrectly accepted"})
        (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 1
    report["steps"].append({
        "step": "adversarial_tamper", "status": "ok",
        "problems": tamper_check["problems"],
    })

    # 10. Historical cutoff refusal
    early = answers.lookup_bound(binding, "2017-01-01T00:00:00Z")
    if early.get("outcome") == "answered":
        report["steps"].append({"step": "cutoff_refusal", "status": "failed", "answer": early})
        (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 1
    report["steps"].append({
        "step": "cutoff_refusal", "status": "ok",
        "outcome": early.get("outcome"), "reason": early.get("reason"),
        "problems": (early.get("context") or {}).get("problems"),
    })

    report["status"] = "passed"
    report["claims"] = [
        "3M FY2022 consolidated net sales resolved from a real SEC 10-K with scale=6 (USD millions).",
        "Answer compiled through FEC and independently recomputed with Fraction arithmetic.",
        "Research certificate verified by atlas verify-certificate; value tampering is rejected.",
        "A pre-availability cutoff correctly refuses the same binding.",
    ]
    (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": "passed",
        "value": answer["value"],
        "economic_amount": answer.get("economic_amount"),
        "certificate": str(cert_path),
        "fingerprint": certificate["certificate_fingerprint"],
        "report": str(OUT_DIR / "report.json"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
