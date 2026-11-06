#!/usr/bin/env python
"""Reproduce the exported Phase 9.2 application on a clean schema-13 database."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from atlas.applications.contracts import read_package
from atlas.applications.service import ApplicationService
from atlas.storage.db import Database

ARTIFACT = ROOT / "artifacts" / "phase9_2_application.atlas"
payload = ARTIFACT.read_bytes()
digest = hashlib.sha256(payload).hexdigest()
package = read_package(payload)
regulatory = json.loads(package["files"]["data/regulatory.json"])
holding = regulatory.get("holding_company") or {}
parent = holding.get("parent") or regulatory.get("parent") or {}
latest = holding.get("latest") or {}
subsidiaries = regulatory.get("subsidiaries") or []

with tempfile.TemporaryDirectory() as directory:
    db = Database(Path(directory) / "reproduction.db")
    migrations = db.migrate()
    service = ApplicationService(db)
    install = service.install(payload)
    execution = service.execute(install["install_id"])
    schema = db.schema_version()
    db.close()

result = {
    "schema": "atlas.phase9_2.reproduction.v1",
    "package": {
        "path": ARTIFACT.relative_to(ROOT).as_posix(),
        "bytes": len(payload),
        "sha256": digest,
        "package_sha256": package["package_sha256"],
        "application_id": install["application_id"],
        "price_included": False,
        "contains_restricted_price_289_91": b"289.91" in payload,
        "parent_regulatory": holding.get("status"),
    },
    "fresh_database": "temporary directory, removed after execution",
    "fresh_schema": schema,
    "migrations": migrations,
    "install": {
        "status": install["status"],
        "already_installed": install.get("already_installed"),
        "integrity_status": install.get("reproducibility"),
        "install_id": install["install_id"],
    },
    "execution": {
        "status": execution["status"],
        "reproduced": execution["reproduced"],
        "differences": execution["differences"],
        "model_version": execution["model_version"],
        "valuation_method": execution["valuation_method"],
        "contract_state": execution["contract_state"],
        "outputs": execution["outputs"],
        "expected_outputs": execution["expected_outputs"],
    },
    "source_reconciliation": {
        "issuer_cik": regulatory.get("cik"),
        "period_end": latest.get("period_end"),
        "parent_form": holding.get("form"),
        "parent_rssd": parent.get("rssd"),
        "subsidiary_cert": subsidiaries[0].get("cert") if subsidiaries else None,
    },
    "limitations": [
        "The package reproduces the packaged SEC snapshot and assumptions, not original SEC bytes.",
        "The opening book value is SEC total stockholders' equity less same-period SEC preferred stock; preferred is a GAAP balance-sheet claim, not CET1.",
        "No bulk FR Y-9C release timestamp is available, so point-in-time regulatory reconstruction is not claimed.",
        "The restricted market price is intentionally absent from the package.",
    ],
}

assert result["execution"]["reproduced"] is True, result["execution"]
assert result["execution"]["differences"] == {}, result["execution"]["differences"]
assert result["package"]["sha256"] == result["package"]["package_sha256"]
assert result["package"]["contains_restricted_price_289_91"] is False
assert result["source_reconciliation"]["parent_form"] == "FR Y-9C"
assert result["fresh_schema"] == 13
outputs = result["execution"]["outputs"]
assert outputs["book_value_basis"] == "sec_total_stockholders_equity_less_preferred_stock"
assert outputs["common_equity_status"] == "derived_total_equity_less_preferred_stock"
assert outputs["book_value_total_equity"] == 324_758_000_000 * 0 + 344_758_000_000
assert outputs["preferred_equity"] == 20_050_000_000
assert outputs["book_value_common_equity"] == 324_708_000_000
assert outputs["book_value_used"] == 324_708_000_000
assert abs(outputs["book_value_per_common_share"] - 324_708_000_000 / 2_797_600_000) < 1e-9
assert outputs["reported_roe"] == 56_868_000_000 / 324_708_000_000
assert abs(outputs["value_per_share"] - 287.919648765908) < 0.01

out = ROOT / "artifacts" / "phase9_2_reproduction.json"
out.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({
    "exit": 0,
    "package_sha256": digest,
    "differences": result["execution"]["differences"],
    "value_per_share": result["execution"]["outputs"]["value_per_share"],
    "parent_form": result["source_reconciliation"]["parent_form"],
}, indent=2))
