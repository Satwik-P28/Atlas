#!/usr/bin/env python
"""Import market observations for research with explicit, auditable rights.

Two modes:

1. **Default - distributable synthetic fixture.** Imports
   ``fixtures/market/synthetic_prices.csv`` for the project's synthetic issuer. These are
   generated values that Atlas authored; they exist so the ingestion, revision, session
   identity and selection paths run in CI without redistributing anybody's price history.
   Nothing about them is real and the source row says so.

2. **User-supplied licensed data.** ``--csv PATH --ticker T --source-name NAME
   --licence TERMS --redistribution {restricted,user_responsibility,private,public_domain}``
   imports a file the operator is entitled to use. Atlas never fetches it, never guesses
   its licence, and never exports it unless the declared terms permit redistribution.

The script performs no network collection.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.entities.master import SecurityMaster  # noqa: E402
from atlas.research.prices import import_price_series  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import SourceRegistry, ensure_default_sources  # noqa: E402

MARKET = ROOT / "fixtures" / "market"
SYNTHETIC_TICKER = "ATLS"
SYNTHETIC_CIK = "0009999999"
SYNTHETIC_ISSUER = "Atlas Synthetic Markets Corp"
SYNTHETIC_MIC = "XNAS"
SYNTHETIC_RETRIEVED_AT = "2024-12-13T21:00:00Z"


def ensure_synthetic_identity(db: Database) -> str:
    """Register (or reuse) the synthetic issuer, security, listing and ticker."""
    ensure_default_sources(db)
    registry_source = SourceRegistry(db).ensure_custom(
        "Atlas synthetic identity registry",
        kind="synthetic",
        licence="Apache-2.0 (project-authored identity record)",
        redistribution="public_domain",
        notes=(
            "Registers the synthetic issuer/security used by the distributable market "
            "fixture. Not an exchange assignment and not a claim about any real issuer."
        ),
        source_id="atlas-synthetic-fixtures",
    )
    master = SecurityMaster(db)
    master.ensure_venue(SYNTHETIC_MIC, "Nasdaq", country="US", timezone="America/New_York")
    resolution = master.resolve_ticker(SYNTHETIC_TICKER)
    if len({candidate.security_id for candidate in resolution.candidates}) == 1:
        return resolution.candidates[0].security_id
    try:
        issuer = master.require_issuer_by_cik(SYNTHETIC_CIK)
    except Exception:  # noqa: BLE001 - the issuer does not exist yet
        master.register_issuer(legal_name=SYNTHETIC_ISSUER, cik=SYNTHETIC_CIK, sic="9999")
        issuer = master.require_issuer_by_cik(SYNTHETIC_CIK)
    securities = master.securities_for_issuer(issuer["issuer_id"])
    if securities:
        security_id = securities[0]["security_id"]
    else:
        security_id = master.ensure_security(
            issuer["issuer_id"], class_designation="common stock", currency="USD"
        )
    listings = [item for item in master.listings(security_id) if str(item["mic"]).upper() == SYNTHETIC_MIC]
    if listings:
        listing_id = listings[0]["listing_id"]
    else:
        listing_id = master.ensure_listing(
            security_id, SYNTHETIC_MIC, valid_from="2019-01-01", is_primary=True
        )
    master.assign_ticker(
        listing_id,
        SYNTHETIC_TICKER,
        valid_from="2019-01-01",
        confidence=1.0,
        status="confirmed",
        source_id=registry_source,
        evidence_note="Project-authored synthetic fixture; not an exchange assignment.",
    )
    return security_id


def read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def import_synthetic(db: Database, manifest: dict[str, Any]) -> dict[str, Any]:
    security_id = ensure_synthetic_identity(db)
    series = manifest["series"][0]
    rows = read_rows(ROOT / series["path"])
    imported = import_price_series(
        db,
        ticker=SYNTHETIC_TICKER,
        rows=rows,
        source_name="Atlas synthetic market fixture",
        licence=manifest["licence"],
        redistribution=manifest["redistribution"],
        adjustment_semantics=manifest["adjustment_semantics"],
        retrieved_at=SYNTHETIC_RETRIEVED_AT,
        currency="USD",
        authorization_basis=manifest["authorization_basis"],
        collection_method="synthetic_fixture",
        security_id=security_id,
        mic=SYNTHETIC_MIC,
    )
    return {
        "ticker": SYNTHETIC_TICKER,
        "security_id": security_id,
        "synthetic": True,
        "rows": len(rows),
        "import": imported,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="var/phase9.db")
    parser.add_argument("--csv", help="a market CSV the operator is entitled to use")
    parser.add_argument("--ticker")
    parser.add_argument("--source-name")
    parser.add_argument("--licence")
    parser.add_argument(
        "--redistribution",
        default="restricted",
        choices=["public_domain", "user_responsibility", "restricted", "private"],
    )
    parser.add_argument("--authorization-basis")
    parser.add_argument("--adjustment-semantics", default="unadjusted")
    parser.add_argument("--security-id")
    parser.add_argument("--mic")
    parser.add_argument("--retrieved-at")
    args = parser.parse_args()

    path = Path(args.db)
    if not path.is_absolute():
        path = ROOT / path
    db = Database(path)
    db.migrate()

    results: list[dict[str, Any]] = []
    if args.csv:
        required = ("ticker", "source_name", "licence")
        missing = [name for name in required if not getattr(args, name)]
        if missing:
            print(
                "a user-supplied import requires " + ", ".join("--" + name.replace("_", "-") for name in missing),
                file=sys.stderr,
            )
            return 2
        csv_path = Path(args.csv)
        if not csv_path.is_absolute():
            csv_path = ROOT / csv_path
        if not csv_path.exists():
            print(f"no such CSV: {csv_path}", file=sys.stderr)
            return 2
        imported = import_price_series(
            db,
            ticker=args.ticker,
            rows=read_rows(csv_path),
            source_name=args.source_name,
            licence=args.licence,
            redistribution=args.redistribution,
            adjustment_semantics=args.adjustment_semantics,
            retrieved_at=args.retrieved_at,
            authorization_basis=args.authorization_basis,
            collection_method="user_import",
            security_id=args.security_id,
            mic=args.mic,
        )
        results.append({"ticker": args.ticker, "synthetic": False, "import": imported})
    else:
        manifest = json.loads((MARKET / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("synthetic") is not True or manifest.get("contains_vendor_data") is not False:
            print(
                "refusing to bootstrap from a manifest that is not declared synthetic and vendor-free",
                file=sys.stderr,
            )
            return 2
        results.append(import_synthetic(db, manifest))

    print(json.dumps({
        "schema": "atlas.market_data.bootstrap.v2",
        "database": str(path),
        "results": results,
        "rights_note": (
            "The bootstrap fixture is project-authored and synthetic: redistributable, and "
            "never to be described as observed market data. Observations imported from a "
            "vendor remain local under the terms the operator declared and are excluded "
            "from research packages unless redistribution was explicitly granted."
        ),
    }, indent=2, sort_keys=True))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
