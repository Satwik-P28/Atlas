#!/usr/bin/env python
"""Render the human-readable traceability matrix and ICB scoreboard from the registries.

The JSON registries are the data; these documents are their readable projection. Rendering
(rather than hand-maintaining a second copy) is what keeps a requirement's status and its
evidence from drifting apart.

Run: python scripts/render_spec_registries.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
DOCS = ROOT / "docs"


def _load(name: str) -> dict:
    return json.loads((ARTIFACTS / name).read_text())


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|").strip()


def render_traceability(payload: dict) -> str:
    spec = payload["specification"]
    entries = payload["requirements"]
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    partial = sum(1 for entry in entries if entry["internally_partial"])

    lines = [
        "# Master specification traceability",
        "",
        "Status: **received_integrity_verified** — the canonical v3.0.0 document is present and",
        "byte-verified. This proves the document's identity, not implementation conformance.",
        "",
        "## Canonical specification",
        "",
        "| Property | Verified value |",
        "| --- | --- |",
        f"| File | `{spec['path']}` (repository root) |",
        f"| Version | {spec['version']} |",
        f"| Date | {spec['date']} |",
        f"| Size | {spec['bytes']:,} bytes |",
        f"| SHA-256 | `{spec['sha256']}` |",
        f"| Sections | 1–{max(spec['sections'])} (all present) |",
        f"| Integrity verified | {spec['integrity_verified_at']} by `{spec['verified_by']}` |",
        f"| Verification commit | `{payload['verification_commit']}` |",
        "",
        "Reproduce:",
        "",
        "```bash",
        "python scripts/verify_master_spec.py",
        "sha256sum ATLAS_MASTER_SPEC.md",
        "python scripts/build_master_spec_registries.py",
        "python scripts/render_spec_registries.py",
        "python -m pytest tests/test_phase9_2_8_master_spec_registry.py",
        "```",
        "",
        "## What the status means",
        "",
        "Statuses use only the Section 60.2 publication vocabulary. `internally_partial` is a",
        "planning flag recorded beside the status, never a replacement for it.",
        "",
    ]
    for name, meaning in payload["status_meanings"].items():
        lines.append(f"- `{name}` — {meaning}")
    lines += [
        "",
        "A capability is not marked implemented because a module or class of similar name exists.",
        "A benchmark is not marked passed because unit tests are green. Nothing in this repository",
        "reaches `production_eligible`: that requires security, correctness, data-rights, performance",
        "and operating gates for a named scope, and none has been run.",
        "",
        "## Counts",
        "",
        f"{len(entries)} requirements mapped across {len(spec['sections'])} canonical sections "
        f"({partial} internally recorded as partial).",
        "",
        "| Status | Requirements |",
        "| --- | --- |",
    ]
    for name in payload["status_vocabulary"]:
        if counts.get(name):
            lines.append(f"| `{name}` | {counts[name]} |")
    lines += [
        "",
        "## Requirement matrix",
        "",
        "Machine-readable source: `artifacts/master_spec_requirements.json`.",
        "",
        "| ID | § | Section | Subsystem | Status | Partial | Evidence | Unimplemented dependency | Sev | Pri |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in entries:
        lines.append(
            "| {id} | {section} | {title} | {subsystem} | `{status}` | {partial} | {evidence} | {gap} | {sev} | {prio} |".format(
                id=entry["requirement_id"],
                section=entry["section"],
                title=_cell(entry["section_title"]),
                subsystem=_cell(entry["subsystem"]),
                status=entry["status"],
                partial="yes" if entry["internally_partial"] else "no",
                evidence=_cell(entry["implementation_evidence"]),
                gap=_cell(entry["unimplemented_dependencies"]),
                sev=entry["severity"],
                prio=entry["priority"],
            )
        )
    lines += [
        "",
        "## Historical record, preserved",
        "",
        "Earlier checkpoints (`docs/MASTER_SPEC_TRACEABILITY.md` before this revision and",
        "`docs/MASTER_SPEC_GATE.md`) correctly reported that the then-expected v1.2.0 document",
        "(155,419 bytes, SHA-256 `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`)",
        "was absent, and refused to map requirements from an invented copy. Those reports were",
        "accurate for their checkpoints and are not rewritten here. The current canonical document",
        "is v3.0.0 at the size and hash above; the v1.2 hash must not be presented as matching it.",
        "",
        "The earlier statement that \"the only ICB identifiers defined anywhere in this repository are",
        "ICB-04 and ICB-09\" was also correct at that time: ICB-01 through ICB-48 are now read from",
        "the canonical document and registered in `artifacts/icb_registry.json`.",
        "",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_scoreboard(icb: dict) -> str:
    entries = icb["benchmarks"]
    counts = icb["summary"]["counts_by_status"]
    lines = [
        "# Institutional capability scoreboard",
        "",
        "ICB-01 through ICB-48 as defined by the canonical v3.0.0 specification (Sections 22, 48",
        "and 60). Machine-readable source: `artifacts/icb_registry.json`.",
        "",
        "## Acceptance rule",
        "",
        icb["acceptance_rule"],
        "",
        "Consequences applied here:",
        "",
        "- A benchmark is `prototype_verified` only where a named test or audit in this repository",
        "  exercises the stated acceptance case; that still does not establish the professional",
        "  workflow was independently validated.",
        "- A model audit that checks arithmetic supports a benchmark; it does not accept it.",
        "- No benchmark is marked executed in Phase 9.2.8. Nothing here is `production_eligible`.",
        "- Suites that require licensed market data, exchange products or broker access are marked",
        "  `vision_only` and are blocked on entitlement, not on engineering alone.",
        "",
        "## Summary",
        "",
        f"Total benchmarks: {icb['summary']['total']}.",
        "",
        "| Status | Count |",
        "| --- | --- |",
    ]
    for name in icb["status_vocabulary"]:
        if counts.get(name):
            lines.append(f"| `{name}` | {counts[name]} |")
    lines += [
        "",
        "## Priority order",
        "",
        "| Priority | Benchmarks |",
        "| --- | --- |",
    ]
    for priority in ("P0", "P1", "P2", "P3", "P4"):
        ids = [entry["benchmark_id"] for entry in entries if entry["priority"] == priority]
        if ids:
            lines.append(f"| {priority} | {', '.join(ids)} |")
    lines += ["", "## ICB-01 to ICB-48", ""]
    for entry in entries:
        number = entry["benchmark_id"]
        lines += [
            f"### {number} — {entry['name']}",
            "",
            f"| Field | Value |",
            f"| --- | --- |",
            f"| Status | `{entry['status']}` |",
            f"| Priority | {entry['priority']} |",
            f"| Specification | v{entry['spec_version']}, Section {entry['spec_section']} |",
            f"| Objective | {_cell(entry['objective'])} |",
            f"| Input dataset | {_cell(entry['input_dataset'])} |",
            f"| Legal data entitlement | {_cell(entry['legal_data_entitlement'])} |",
            f"| Independent baseline | {_cell(entry['independent_baseline'])} |",
            f"| Required outputs | {_cell(entry['required_outputs'])} |",
            f"| Acceptance criteria | {_cell(entry['acceptance_criteria'])} |",
            f"| Existing tests | {', '.join('`' + item + '`' for item in entry['existing_tests']) or 'none'} |",
            f"| Adversarial cases | {_cell(entry['adversarial_cases'])} |",
            f"| Evidence available | {_cell(entry['evidence_available'])} |",
            f"| Missing implementation | {_cell(entry['missing_implementation'])} |",
            f"| Dependencies | {', '.join(entry['dependencies'])} |",
            f"| Executed | {'yes' if entry['executed'] else ('no' if entry['executed'] is False else 'not recorded')} |",
            f"| Recorded | {entry['verification_date']} at `{entry['commit_sha']}` |",
            "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def main() -> int:
    payload = _load("master_spec_requirements.json")
    icb = _load("icb_registry.json")
    (DOCS / "MASTER_SPEC_TRACEABILITY.md").write_text(render_traceability(payload))
    (DOCS / "INSTITUTIONAL_CAPABILITY_SCOREBOARD.md").write_text(render_scoreboard(icb))
    print("wrote docs/MASTER_SPEC_TRACEABILITY.md and docs/INSTITUTIONAL_CAPABILITY_SCOREBOARD.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
