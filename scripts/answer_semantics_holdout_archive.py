"""Verify the archived prospective holdout without touching today's resolver.

The first scored run is historical evidence. Its audit must keep working after the resolver is
developed further, so this script never hashes the working tree's code: it reads the frozen
inputs, the preregistration and the resolution code **as committed at the commits they name**,
using ``git cat-file``. Only the preserved artifact and the one ledger of gold decisions are
compared with their working copies.

It also records what the scored run actually contains, including the abstentions on answerable
questions that the headline ``resolution_failures`` field does not count.

Usage::

    python scripts/answer_semantics_holdout_archive.py --write   # first time only
    python scripts/answer_semantics_holdout_archive.py --check   # every audit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research import holdout  # noqa: E402

ARCHIVE_PATH = holdout.ARTIFACTS / "holdout_archive_manifest.json"
#: The commits the record names. A new evaluation gets a new record; this one is closed.
GOLD_COMMIT = "8da2269"
FREEZE_COMMIT = "62d392b"
RUN_COMMIT = "7d3e509"
REPORT_COMMIT = "1c5dea5"
HEAD_AT_AUDIT = "0090573"
CI_RUNS = [
    {"workflow": "CI", "run_number": 64, "run_id": 45270236799, "commit": "5cf7726",
     "conclusion": "success"},
    {"workflow": "CI", "run_number": 65, "run_id": 45271271720, "commit": "0090573",
     "conclusion": "success"},
]


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _git(*args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.decode()[:300]
        if _is_shallow_or_truncated():
            detail += ("\nthis checkout has no history for the named commits; the audit needs a "
                       "full clone (git fetch --unshallow, or actions/checkout with "
                       "fetch-depth: 0)")
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _is_shallow_or_truncated() -> bool:
    result = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=ROOT,
                            capture_output=True)
    return result.returncode == 0 and result.stdout.strip() == b"true"


def _blob_at(commit: str, path: str) -> bytes:
    return _git("cat-file", "-p", f"{commit}:{path}")


def _verdict(name: str, actual: str, expected: str) -> dict[str, Any]:
    return {"check": name, "ok": actual == expected, "actual": actual, "expected": expected}


def audit() -> dict[str, Any]:
    freeze = json.loads(holdout.FREEZE_PATH.read_text())
    artifact = json.loads(holdout.OUTPUT_PATH.read_text())
    observed: list[dict[str, Any]] = []

    # 1. Frozen inputs: the bytes at the freeze commit must still hash to the recorded digests.
    for path, expected in sorted(freeze["inputs"].items()):
        if path == holdout.AUTHOR_SCRIPT or path.startswith("fixtures/"):
            commit = GOLD_COMMIT if path.endswith(("questions.json", "facts.json", "ledger.json")) \
                else FREEZE_COMMIT
        else:
            commit = FREEZE_COMMIT
        observed.append(_verdict(f"input_at_{commit}:{path}", _digest(_blob_at(commit, path)),
                                 expected))

    # 2. Resolution code as it existed for the scored run: the freeze records the commit, and the
    #    code bytes at that commit are what actually ran. Today's source may differ.
    for path, expected in sorted(freeze["code"].items()):
        observed.append(_verdict(f"code_at_{freeze['code_commit'][:7]}:{path}",
                                 _digest(_blob_at(freeze["code_commit"], path)), expected))
    current = {path: _digest((ROOT / path).read_bytes()) for path in sorted(holdout.FROZEN_CODE)}
    drifted = [path for path, digest in current.items()
               if digest != _digest(_blob_at(freeze["code_commit"], path))]

    # 3. The preserved artifact must be byte-identical to the committed first run.
    committed_artifact = _digest(_blob_at(RUN_COMMIT, "artifacts/answer_semantics/holdout_evaluation.json"))
    observed.append(_verdict("first_run_artifact_committed", _digest(holdout.OUTPUT_PATH.read_bytes()),
                             committed_artifact))

    # 4. Gold digest recomputed from the preserved files.
    gold = holdout.gold_digest(
        json.loads(holdout.QUESTIONS_PATH.read_text()), json.loads(holdout.FACTS_PATH.read_text()),
        json.loads(holdout.LEDGER_PATH.read_text()), json.loads(holdout.CORPUS_PATH.read_text()),
        json.loads(holdout.PROTOCOL_PATH.read_text()))
    observed.append(_verdict("gold_digest", gold, freeze["gold_digest"]))

    # 5. What the run contains, per arm, including abstentions the headline metric omits.
    results = artifact["results"]
    counts: dict[str, Any] = {}
    for runner in ("baseline", "geometry"):
        arm = [item for item in results if item["runner"] == runner]
        answerable = [item for item in arm if item["gold_class"] == "xbrl_verified"]
        abstained = [item for item in answerable if item["outcome"] != "answered"]
        counts[runner] = {
            "results": len(arm),
            "answerable": len(answerable),
            "answered": len(answerable) - len(abstained),
            "answerable_abstentions": len(abstained),
            "unjustified_abstentions": sum(1 for item in answerable
                                           if item["status"] == "unjustified_abstention"),
            "resolution_failures": sum(1 for item in answerable
                                       if item["status"] == "resolution_failure"),
            "false_answers": sum(1 for item in answerable if item["status"] == "false_answer"),
            "citation_failures": sum(1 for item in answerable
                                     if item["status"] == "citation_failure"),
            "abstention_ids": {
                "unjustified": [item["id"] for item in answerable
                                if item["status"] == "unjustified_abstention"],
                "resolution_failure": [item["id"] for item in answerable
                                       if item["status"] == "resolution_failure"],
            },
        }

    return {
        "schema": "atlas.answer_semantics.holdout_archive_manifest.v1",
        "purpose": ("Append-only audit record of the first prospective holdout. Verifies the "
                    "frozen inputs and resolution code at the commits they name, not the working "
                    "tree, so later development cannot invalidate the experiment's provenance."),
        "historical_label": "first_prospective_holdout_run",
        "commits": {"gold": GOLD_COMMIT, "freeze": FREEZE_COMMIT, "first_run": RUN_COMMIT,
                    "report": REPORT_COMMIT, "head_at_audit": HEAD_AT_AUDIT},
        "ci_runs": CI_RUNS,
        "gold_digest": freeze["gold_digest"],
        "artifact": {"path": str(holdout.OUTPUT_PATH.relative_to(ROOT)),
                     "sha256": _digest(holdout.OUTPUT_PATH.read_bytes()),
                     "schema": artifact.get("schema")},
        "gold_files": {str(path.relative_to(ROOT)): holdout.file_digest(path)
                       for path in (holdout.QUESTIONS_PATH, holdout.FACTS_PATH, holdout.LEDGER_PATH,
                                    holdout.CORPUS_PATH, holdout.PROTOCOL_PATH,
                                    holdout.FREEZE_PATH, holdout.MANIFEST_PATH)},
        "counts": counts,
        "checks": observed,
        "live_code_drifted_from_freeze": drifted,
        "limitations": [
            "CI conclusions are recorded from the hosted run pages; they are not recomputable "
            "offline.",
            "Gold was authored by one reviewer. Printed cells and same-accession XBRL facts were "
            "cross-checked, which is not independent human annotation.",
            "Two labels are contested after the run and are adjudicated separately; the frozen "
            "labels are unchanged.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="create the record if absent")
    parser.add_argument("--check", action="store_true", help="verify the record")
    args = parser.parse_args(argv)
    payload = audit()
    failures = [check for check in payload["checks"] if not check["ok"]]
    if args.write:
        if ARCHIVE_PATH.exists():
            print(f"refusing to rewrite the append-only archive record at {ARCHIVE_PATH}",
                  file=sys.stderr)
            return 1
        ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"wrote {ARCHIVE_PATH}")
    if args.check or not args.write:
        if not ARCHIVE_PATH.exists():
            print(f"no archive record at {ARCHIVE_PATH}; run --write once", file=sys.stderr)
            return 2
        recorded = json.loads(ARCHIVE_PATH.read_text())
        drift = [key for key in ("artifact", "gold_files", "counts", "gold_digest")
                 if recorded.get(key) != payload.get(key)]
        if drift:
            print(f"archive record disagrees with the preserved evidence: {drift}", file=sys.stderr)
            return 1
        print(f"archive verified: {len(payload['checks'])} hash checks, "
              f"{len(payload['live_code_drifted_from_freeze'])} live code files differ from the "
              f"frozen resolver (expected after hardening)")
    if failures:
        for check in failures:
            print(f"FAILED {check['check']}: {check['actual']} != {check['expected']}",
                  file=sys.stderr)
        return 1
    for runner, counts in payload["counts"].items():
        print(f"{runner}: answerable {counts['answerable']}, answered {counts['answered']}, "
              f"answerable abstentions {counts['answerable_abstentions']} "
              f"(unjustified {counts['unjustified_abstentions']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
