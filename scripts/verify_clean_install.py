#!/usr/bin/env python
"""Exercise the clean-install research loop on committed fixtures only.

Given a demo database built by ``scripts/build_terminal_db.py`` (whose market series is
synthetic and redistributable), this script:

1. runs a supported research model on a source-backed company;
2. saves the research application and reopens it;
3. exports a portable ``.atlas`` package;
4. installs and executes that package on a brand-new database in a temporary directory;
5. compares the two executions and reports any difference.

It performs no network access and needs no private data. Exit status is 0 only when the
package reproduces exactly.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.applications.contracts import read_package  # noqa: E402
from atlas.applications.service import ApplicationService  # noqa: E402
from atlas.research.equity import EquityResearchService  # noqa: E402
from atlas.storage.db import Database  # noqa: E402


def build_package(db: Database) -> tuple[dict, bytes]:
    service = EquityResearchService(db)
    created = service.create_package("AAPL", as_of="2025-06-30")
    payload = created["payload"]
    package = read_package(payload)
    return {
        "application_id": package["manifest"]["application"]["application_id"],
        "package_sha256": package["package_sha256"],
        "bytes": len(payload),
        "price_included": bool(package["manifest"]["application"]["state"].get("price_included")),
    }, payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-db", default="var/atlas.db")
    args = parser.parse_args()

    path = Path(args.demo_db)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"missing demo database: {path}; run scripts/build_terminal_db.py first")
        return 1

    # The package is built from the demo database, then installed, reopened and executed
    # in a brand-new database so the loop proves portability rather than reusing state.
    source = Database(path, create=False)
    summary, payload = build_package(source)
    source.close()

    with tempfile.TemporaryDirectory() as directory:
        clean = Database(Path(directory) / "clean.db")
        clean.migrate()
        service = ApplicationService(clean)
        installed = service.install(payload)
        try:
            reopened = service.get(installed["install_id"])
        except Exception:  # noqa: BLE001 - a missing installation is a verification failure
            print("save/reopen failed: the installed application could not be read back")
            return 1
        executed = service.execute(installed["install_id"])
        clean.close()

    differences = {
        key: {"actual": executed["outputs"].get(key), "expected": executed["expected_outputs"].get(key)}
        for key in executed["expected_outputs"]
        if executed["outputs"].get(key) != executed["expected_outputs"].get(key)
    }

    result = {
        "schema": "atlas.clean_install.v1",
        "demo_database": path.relative_to(ROOT).as_posix(),
        "package": summary,
        "saved_and_reopened": {
            "application_id": reopened.get("application_id"),
            "install_id": reopened.get("install_id"),
            "status": reopened.get("status"),
        },
        "clean_database_execution": {
            "status": executed["status"],
            "reproduced": executed["reproduced"],
            "differences": differences,
            "value_per_share": executed["outputs"].get("value_per_share"),
        },
        "network_used": False,
        "private_data_required": False,
    }
    ok = executed["reproduced"] is True and differences == {}
    result["status"] = "pass" if ok else "fail"
    print(json.dumps(result, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
