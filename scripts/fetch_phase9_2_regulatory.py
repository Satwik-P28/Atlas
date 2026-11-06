#!/usr/bin/env python
"""Ingest FDIC Call Report fixtures and verify the parent/subsidiary entity map.

The fixtures were retrieved from the public FDIC BankFind API. This script never invents
a regulatory observation: if a fixture is absent, the issuer is reported as not ingested.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research import regulatory  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

FIXTURES = ROOT / "fixtures" / "regulatory"
CIKS = ("19617", "886982", "731766")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="var/phase9.db")
    args = parser.parse_args()
    path = Path(args.db)
    if not path.is_absolute():
        path = ROOT / path
    db = Database(path)
    db.migrate()
    regulatory.seed_entities(db)
    results = []
    for fixture in sorted(FIXTURES.glob("fdic_*.json")):
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        result = regulatory.ingest_fdic_payload(db, payload)
        results.append({"fixture": fixture.name, **result})
    mappings = {cik: regulatory.reconcile_entities(db, cik) for cik in CIKS}
    summary = {
        "schema": "atlas.regulatory.bootstrap.v1",
        "database": str(path),
        "ingested": results,
        "entities": {
            "verified": sum(1 for item in mappings.values() if item["status"] == "verified"),
            "mapped": sum(1 for item in mappings.values() if item["mapped"]),
        },
        "narrative": (
            "Call Reports describe insured subsidiaries; SEC facts describe the consolidated "
            "parent. The two are linked for research and never summed."
        ),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
