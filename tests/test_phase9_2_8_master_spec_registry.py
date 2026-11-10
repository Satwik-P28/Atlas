"""Phase 9.2.8: validate the master-specification requirement and ICB registries.

The registries are evidence artefacts, so they are checked mechanically rather than
believed:

* the canonical specification's size and SHA-256 in the registry must match the bytes on
  disk, and its version must be the current one (a stale version is a failure);
* every canonical section 1-61 is covered exactly once, requirement ids are unique and
  well formed, and each record carries the status vocabulary, severity, priority,
  verification date and verification commit;
* every referenced source module and test file must exist, so a renamed or deleted module
  cannot leave a requirement claiming evidence that is no longer there;
* the ICB registry covers ICB-01 through ICB-48 exactly once with Section 60 fields, and
  the rendered documents cite every id they claim to carry.

A green run proves the registries are internally consistent with the repository. It does
not prove the implementation status assigned to any requirement: that is what the tests
and audits named in each record are for.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "artifacts" / "master_spec_requirements.json"
ICB = ROOT / "artifacts" / "icb_registry.json"
TRACEABILITY = ROOT / "docs" / "MASTER_SPEC_TRACEABILITY.md"
SCOREBOARD = ROOT / "docs" / "INSTITUTIONAL_CAPABILITY_SCOREBOARD.md"
SPEC = ROOT / "ATLAS_MASTER_SPEC.md"

STATUS_VOCABULARY = [
    "vision_only",
    "implemented_unverified",
    "prototype_verified",
    "implemented_verified",
    "production_eligible",
    "deprecated_or_invalidated",
]
STATUS_SET = set(STATUS_VOCABULARY)
CURRENT_VERSION = "3.0.0"
SPEC_BYTES = 289_963
SPEC_SHA256 = "c1228db93e66a04fb211bea85f6c978289a6040b1f655f934da76498c8c4752d"
SEVERITIES = {"critical", "high", "medium", "low"}
REQUIREMENT_ID = re.compile(r"^MS3-\d{2}$")
ICB_ID = re.compile(r"^ICB-\d{2}$")
SHA = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(REQUIREMENTS.read_text())


@pytest.fixture(scope="module")
def icb() -> dict:
    return json.loads(ICB.read_text())


# ------------------------------------------------------------ specification
def test_registry_pins_the_specification_actually_on_disk(payload):
    specification = payload["specification"]
    assert specification["version"] == CURRENT_VERSION
    assert specification["bytes"] == SPEC_BYTES
    assert specification["sha256"] == SPEC_SHA256
    assert SPEC.exists()
    blob = SPEC.read_bytes()
    assert len(blob) == specification["bytes"]
    assert hashlib.sha256(blob).hexdigest() == specification["sha256"]
    assert specification["status"] == "received_integrity_verified"


def test_no_requirement_carries_an_outdated_specification_version(payload):
    stale = [
        entry["requirement_id"]
        for entry in payload["requirements"]
        if entry["spec_version"] != CURRENT_VERSION
    ]
    assert stale == []
    assert payload["specification"]["version"] == CURRENT_VERSION
    assert payload["status_vocabulary"] == STATUS_VOCABULARY


# ------------------------------------------------------------ requirements
def test_every_canonical_section_is_covered_exactly_once(payload):
    sections = [entry["section"] for entry in payload["requirements"]]
    assert sorted(sections) == list(range(1, 62))
    assert len(sections) == len(set(sections))
    assert payload["specification"]["sections"] == list(range(1, 62))


def test_requirement_ids_are_unique_and_well_formed(payload):
    identifiers = [entry["requirement_id"] for entry in payload["requirements"]]
    assert len(identifiers) == len(set(identifiers))
    assert all(REQUIREMENT_ID.match(identifier) for identifier in identifiers)
    # The id must agree with the section it claims to map.
    for entry in payload["requirements"]:
        assert entry["requirement_id"] == f"MS3-{entry['section']:02d}"


def test_every_requirement_carries_the_required_fields(payload):
    for entry in payload["requirements"]:
        identifier = entry["requirement_id"]
        assert entry["section_title"].strip(), identifier
        assert entry["requirement"].strip(), identifier
        assert entry["subsystem"].strip(), identifier
        assert entry["status"] in STATUS_SET, identifier
        assert entry["severity"] in SEVERITIES, identifier
        assert re.match(r"^P[0-4]$", entry["priority"]), identifier
        assert entry["verification_date"] == "2026-11-10", identifier
        assert SHA.match(entry["commit_sha"]), identifier
        assert isinstance(entry["internally_partial"], bool), identifier
        assert isinstance(entry["source_modules"], list), identifier
        assert isinstance(entry["tests"], list), identifier
        assert entry["unimplemented_dependencies"].strip(), identifier


def test_every_referenced_module_and_test_exists(payload):
    """A stale path would make a requirement point at evidence that no longer exists."""
    missing: list[str] = []
    for entry in payload["requirements"]:
        for relative in entry["source_modules"] + entry["tests"]:
            candidate = ROOT / "src" / relative if relative.startswith("atlas/") else ROOT / relative
            if not candidate.exists():
                missing.append(f"{entry['requirement_id']}:{relative}")
    assert missing == []


def test_production_eligible_is_not_claimed_anywhere(payload):
    """No requirement passed security, correctness, rights and operating gates for a scope."""
    claimed = [e["requirement_id"] for e in payload["requirements"] if e["status"] == "production_eligible"]
    assert claimed == []


# -------------------------------------------------------------------- ICB
def test_icb_registry_covers_all_forty_eight_benchmarks(icb):
    identifiers = [entry["benchmark_id"] for entry in icb["benchmarks"]]
    assert len(identifiers) == 48
    assert len(set(identifiers)) == 48
    assert sorted(identifiers) == [f"ICB-{number:02d}" for number in range(1, 49)]
    assert all(ICB_ID.match(identifier) for identifier in identifiers)


def test_every_icb_entry_carries_the_section_60_fields(icb):
    required = [
        "objective", "input_dataset", "legal_data_entitlement", "independent_baseline",
        "required_outputs", "acceptance_criteria", "adversarial_cases", "status",
        "evidence_available", "missing_implementation", "priority", "dependencies",
    ]
    for entry in icb["benchmarks"]:
        identifier = entry["benchmark_id"]
        assert entry["spec_version"] == CURRENT_VERSION, identifier
        assert entry["status"] in STATUS_SET, identifier
        assert isinstance(entry["existing_tests"], list), identifier
        assert re.match(r"^P[0-4]$", entry["priority"]), identifier
        assert isinstance(entry["dependencies"], list) and entry["dependencies"], identifier
        for field in required:
            if field == "dependencies":
                continue
            value = entry[field]
            assert isinstance(value, str) and value.strip(), f"{identifier}:{field}"
        assert SHA.match(entry["commit_sha"]), identifier


def test_icb_summary_matches_the_entries(icb):
    counts: dict[str, int] = {}
    for entry in icb["benchmarks"]:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    assert icb["summary"]["total"] == 48
    assert icb["summary"]["counts_by_status"] == dict(sorted(counts.items()))


def test_no_vision_only_benchmark_is_marked_executed(icb):
    for entry in icb["benchmarks"]:
        if entry["status"] in {"vision_only", "implemented_unverified"}:
            assert entry["executed"] is False, entry["benchmark_id"]
        if entry["executed"] is True:
            pytest.fail(f"{entry['benchmark_id']} claims execution; no ICB was executed in 9.2.8")


# ---------------------------------------------------------------- documents
def test_traceability_document_cites_every_requirement(payload):
    text = TRACEABILITY.read_text()
    missing = [entry["requirement_id"] for entry in payload["requirements"] if entry["requirement_id"] not in text]
    assert missing == []
    assert "received_integrity_verified" in text
    assert CURRENT_VERSION in text


def test_scoreboard_cites_every_benchmark(icb):
    text = SCOREBOARD.read_text()
    missing = [entry["benchmark_id"] for entry in icb["benchmarks"] if entry["benchmark_id"] not in text]
    assert missing == []
    assert "ICB-01" in text and "ICB-48" in text
