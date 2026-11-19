"""Browser journeys must not pin a numeric database schema version.

A journey that asserts ``health.schema_version === 13`` fails the moment a legitimate
migration lands, for a reason unrelated to the interface it certifies. That happened when
migration 014 (Phase 9.5) moved the head to 14: four journeys broke before rendering a
single page. They now read the migration head through ``web/e2e/schema.mjs``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E2E = ROOT / "web" / "e2e"
MIGRATIONS = ROOT / "src" / "atlas" / "storage" / "migrations.py"

PIN = re.compile(r"schema_version\s*===\s*\d+")


def test_no_journey_pins_a_numeric_schema_version() -> None:
    offenders = []
    for path in sorted(E2E.glob("*.mjs")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if PIN.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "browser journeys must compare against LATEST_SCHEMA_VERSION from web/e2e/schema.mjs "
        "instead of a literal:\n" + "\n".join(offenders)
    )


def test_the_helper_reads_the_migration_chain_it_claims_to_read() -> None:
    helper = (E2E / "schema.mjs").read_text(encoding="utf-8")
    assert "src/atlas/storage/migrations.py" in helper, (
        "schema.mjs must read the migration chain rather than a copy of the number"
    )
    # The helper's pattern must still match the way migrations are declared in Python.
    entries = MIGRATIONS.read_text(encoding="utf-8")
    assert re.search(r"Migration\(\s*version=\d+", entries), (
        "migrations.py no longer declares versions in the form the helper parses"
    )
    assert "Migration\\(\\s*version=(\\d+)" in helper, (
        "schema.mjs no longer parses Migration(version=N, ...) declarations"
    )
