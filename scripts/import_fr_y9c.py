#!/usr/bin/env python
"""Import a locally retained official FFIEC FR Y-9C BHCF archive.

The script never fetches from FFIEC. The operator obtains the quarterly ZIP from the
published NIC Financial Data Download page and passes its local path. The exact bytes,
SHA-256, legal entity, reporting period and every selected MDRM value are recorded.

Example:
    .venv/bin/python scripts/import_fr_y9c.py \
        --db var/phase9.db \
        --archive fixtures/regulatory/BHCF20241231.ZIP \
        --dictionary fixtures/regulatory/Financial_Download_Dictionary.xlsx \
        --cik 19617 --entity REG-JPM-PARENT
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research import fr_y9c  # noqa: E402
from atlas.storage.db import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="var/phase9.db")
    parser.add_argument(
        "--archive", default="fixtures/regulatory/BHCF20241231.ZIP",
        help="locally retained official FFIEC BHCF quarterly ZIP",
    )
    parser.add_argument(
        "--dictionary", default="fixtures/regulatory/Financial_Download_Dictionary.xlsx",
        help="official FFIEC Financial Download Dictionary",
    )
    parser.add_argument("--cik", default="19617")
    parser.add_argument("--entity", default="REG-JPM-PARENT")
    parser.add_argument("--rssd", default=None)
    parser.add_argument(
        "--published-at", default=None,
        help="only when an official release timestamp is verified; never inferred",
    )
    parser.add_argument("--publication-basis", default=None)
    parser.add_argument("--retrieved-at", default=None)
    args = parser.parse_args()
    path = Path(args.db)
    if not path.is_absolute():
        path = ROOT / path
    archive = Path(args.archive)
    if not archive.is_absolute():
        archive = ROOT / archive
    dictionary = Path(args.dictionary)
    if not dictionary.is_absolute():
        dictionary = ROOT / dictionary
    db = Database(path)
    db.migrate()
    result = fr_y9c.ingest_archive(
        db,
        archive,
        dictionary,
        cik=args.cik,
        entity_id=args.entity,
        rssd=args.rssd,
        published_at=args.published_at,
        publication_basis=args.publication_basis,
        retrieved_at=args.retrieved_at,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
