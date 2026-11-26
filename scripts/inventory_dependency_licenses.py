#!/usr/bin/env python
"""Inventory every dependency Atlas ships or builds with, and its licence.

Two distinct obligations meet here and must not be confused:

* **Python dependencies** are installed by the user with the package; each keeps its own
  licence and its own notices.
* **Frontend dependencies** are compiled into the bundle that ships inside the wheel. Their
  licences must be reproduced in the distribution's third-party notices, and some (for
  example MPL-2.0 files) impose file-level obligations.

The output is machine-readable (`docs/DEPENDENCY_LICENSES.json`) plus a generated Markdown
summary. Licences are read from installed package metadata and from the npm lockfile and
`node_modules`, never guessed from a package name.

Usage::

    .venv/bin/python scripts/inventory_dependency_licenses.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "atlas.dependency_licenses.v1"

# Packages that are part of a test/development environment only, never of a shipped runtime.
TOOLING = {
    "pytest", "pytest-asyncio", "pytest-cov", "ruff", "mypy", "black", "isort", "coverage",
    "pip-audit", "bandit", "types-requests", "setuptools", "wheel", "build", "twine", "mcp",
}


def normalise(name: str) -> str:
    return name.lower().replace("_", "-").strip()


def declared_python_requirements() -> list[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    names = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        names.extend(extra)
    cleaned: list[str] = []
    for requirement in names:
        name = requirement.split(";")[0].split("[")[0]
        for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", " "):
            name = name.split(separator)[0]
        name = normalise(name)
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def python_inventory() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in declared_python_requirements():
        if name in TOOLING:
            continue
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            rows.append({"name": name, "version": None, "license": None,
                         "status": "not installed in this environment"})
            continue
        meta = distribution.metadata
        license_expression = meta.get("License-Expression")
        license_field = (meta.get("License") or "").strip()
        classifiers = [value for value in meta.get_all("Classifier") or []
                       if value.startswith("License ::")]
        if len(license_field) > 120:  # some projects paste the whole licence text here
            license_field = license_field[:117] + "..."
        licence = license_expression or license_field or (
            classifiers[0].split("::")[-1].strip() if classifiers else None)
        rows.append({
            "name": normalise(name),
            "version": distribution.version,
            "license": licence,
            "license_source": ("License-Expression" if license_expression
                               else "License" if license_field
                               else "classifier" if classifiers else None),
            "home_page": meta.get("Home-page") or meta.get("Project-URL") or None,
        })
    return rows


def npm_inventory() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lock_path = ROOT / "web" / "package-lock.json"
    if not lock_path.is_file():
        return [], []
    packages = json.loads(lock_path.read_text()).get("packages") or {}
    bundled: list[dict[str, Any]] = []
    dev: list[dict[str, Any]] = []
    for path, entry in packages.items():
        if not path.startswith("node_modules/"):
            continue  # the root project entry
        name = entry.get("name") or path.rsplit("node_modules/", 1)[-1]
        licence = entry.get("license")
        if isinstance(licence, list):
            licence = " OR ".join(str(item) for item in licence)
        if not licence:
            package_json = ROOT / "web" / path / "package.json"
            if package_json.is_file():
                licence = json.loads(package_json.read_text()).get("license")
                if isinstance(licence, dict):
                    licence = licence.get("type")
        row = {"name": name, "version": entry.get("version"), "license": licence}
        (dev if entry.get("dev") else bundled).append(row)
    return bundled, dev


def audit_vulnerabilities() -> dict[str, Any]:
    """Run the project's own dependency scan when it is available."""
    script = ROOT / "scripts" / "scan_dependencies.py"
    if not script.is_file():
        return {"status": "NOT RUN", "detail": "scripts/scan_dependencies.py is absent"}
    result = subprocess.run([sys.executable, str(script), "--json"], cwd=str(ROOT),
                            capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        return {"status": "FAIL", "detail": (result.stderr or result.stdout)[-600:]}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "FAIL", "detail": "the scan did not return JSON"}
    return {"status": "PASS",
            "detail": f"{payload.get('findings', len(payload.get('issues') or []))} finding(s)",
            "payload": payload}


def render_markdown(inventory: dict[str, Any]) -> str:
    python_rows = inventory["python"]
    bundled = inventory["npm_bundled"]
    dev = inventory["npm_dev"]
    unknown = [row for row in python_rows if not row.get("license")] + \
              [row for row in bundled if not row.get("license")]

    def table(rows: list[dict[str, Any]]) -> str:
        lines = ["| Package | Version | Licence |", "| --- | --- | --- |"]
        for row in sorted(rows, key=lambda item: item["name"]):
            lines.append(f"| `{row['name']}` | {row.get('version') or '—'} | "
                         f"{row.get('license') or '**not declared**'} |")
        return "\n".join(lines)

    return f"""# Dependency licence inventory

Generated by `scripts/inventory_dependency_licenses.py` at {inventory['generated_at']} from
the installed environment and `web/package-lock.json`. Do not edit by hand.

This file records what the dependencies say about themselves. It is not a legal opinion, and
it does not grant any right: the licence of each dependency governs its own use, and the
Apache-2.0 licence applied to Atlas covers Atlas's own code, documentation and
project-authored synthetic fixtures only.

## Python runtime dependencies ({len(python_rows)})

{table(python_rows)}

## Frontend dependencies bundled into the shipped build ({len(bundled)})

{table(bundled)}

## Frontend development-only dependencies ({len(dev)})

Not shipped. Their licences still apply to the repository's development tooling; the full
list is in the JSON inventory.

## Items needing a maintainer decision

{chr(10).join(f"- `{row['name']}` declares no licence in its metadata" for row in unknown) if unknown else "- None: every dependency declares a licence."}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "DEPENDENCY_LICENSES.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "docs" / "DEPENDENCY_LICENSES.md")
    parser.add_argument("--skip-scan", action="store_true")
    args = parser.parse_args(argv)

    bundled, dev = npm_inventory()
    inventory = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                 capture_output=True, text=True).stdout.strip(),
        "python_version": sys.version.split()[0],
        "python": python_inventory(),
        "npm_bundled": bundled,
        "npm_dev": dev,
        "vulnerability_scan": ({} if args.skip_scan else audit_vulnerabilities()),
        "note": ("Dependency licences are independent of the Atlas licence. Apache-2.0 does "
                 "not relicense any dependency, and no data redistribution right is implied."),
    }
    args.out.write_text(json.dumps(inventory, indent=2) + "\n")
    args.markdown.write_text(render_markdown(inventory))
    missing = [row["name"] for row in inventory["python"] if not row.get("license")]
    print(f"python {len(inventory['python'])}, bundled npm {len(bundled)}, dev npm {len(dev)}, "
          f"missing licence metadata {len(missing)}")
    print(f"wrote {args.out} and {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
