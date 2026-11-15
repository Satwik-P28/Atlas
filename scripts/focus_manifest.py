#!/usr/bin/env python
"""Generate the pinned FOCUS source manifest.

This is a deliberate, separate command. Strict certificate verification reads an existing manifest
and reports missing evidence when it is absent; it never writes one, because a verifier that
manufactures its own trust anchor verifies nothing.

The manifest pins, for every accession a certificate may cite: the document digest, the issuer
identity, and every cell (content-addressed table hash, row, column) with its printed text, period,
scale, currency, concept and availability time. It is derived from the ingested documents and the
resolver bindings, never from a certificate.

    python scripts/focus_manifest.py --db var/focus_demo.db
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.research.certificate_verify import build_source_manifest  # noqa: E402
from atlas.research.focus_cases import run_cases  # noqa: E402
from atlas.storage.db import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="var/focus_demo.db")
    parser.add_argument("--out", default="artifacts/focus_source_manifest.json")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    database = Path(args.db)
    if not database.exists():
        print(json.dumps({
            "status": "CORPUS_MISSING",
            "database": str(database),
            "remedy": "ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com' "
                      "python scripts/focus_build_corpus.py --db " + str(database),
        }, indent=2))
        return 2

    db = Database(str(database))
    results = run_cases(db)
    bindings = [binding for result in results if result.answered for binding in result.bindings]
    if not bindings:
        print(json.dumps({"status": "NO_BINDINGS", "database": str(database)}, indent=2))
        return 2
    manifest = build_source_manifest(db, bindings, generated_at=iso(utcnow()))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    db.close()
    summary = {
        "status": "written",
        "manifest": str(out),
        "documents": len(manifest["documents"]),
        "cells": sum(len(entry["cells"]) for entry in manifest["documents"].values()),
        "answered_cases": sum(1 for result in results if result.answered),
    }
    if not args.quiet:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
