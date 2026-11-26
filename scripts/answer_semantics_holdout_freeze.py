"""Write or verify the prospective holdout preregistration.

``--write`` records SHA-256 hashes of every frozen input and of the resolution code, the cohort
counts, the metric definitions, the analysis plan and the reviewer limitation. It refuses to run
unless the tracked working tree is clean, so the record describes a commit rather than an edit.

``--check`` re-derives the hashes and the committed blobs and fails on any drift. The scoring
script and the test suite both call it; an uncommitted local hash is never treated as evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research import holdout  # noqa: E402

FREEZE = ROOT / "fixtures" / "answer_semantics" / "holdout_freeze.json"


def _git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text())


def _counts() -> dict:
    questions = _load("fixtures/answer_semantics/holdout_questions.json")
    ledger = _load("fixtures/answer_semantics/holdout_ledger.json")
    return {
        "questions": len(questions["questions"]),
        "answerable": sum(1 for q in questions["questions"]
                          if q["gold_class"] == "xbrl_verified"),
        "abstention": sum(1 for q in questions["questions"]
                          if q["gold_class"] != "xbrl_verified"),
        "lookups": sum(1 for q in questions["questions"] if q["operator"] == "lookup"
                       and q["gold_class"] == "xbrl_verified"),
        "arithmetic": sum(1 for q in questions["questions"]
                          if q["operator"] == "percentage_change"),
        "ledger_attempted": ledger["summary"]["attempted"],
        "ledger_scored": ledger["summary"]["scored"],
        "ledger_not_scored": ledger["summary"]["not_scored"],
        "issuers": len({q["issuer_cik"] for q in questions["questions"]}),
        "accessions": len({q["accession"] for q in questions["questions"]}),
    }


def write(reissue: str | None = None) -> int:
    previous = None
    if FREEZE.exists():
        if not reissue:
            raise SystemExit(f"preregistration already exists at {FREEZE}; it is not rewritten")
        prior = json.loads(FREEZE.read_text())
        if prior.get("status") != "frozen_awaiting_first_run":
            raise SystemExit("a preregistration that has already been scored cannot be reissued")
        if holdout.OUTPUT_PATH.exists():
            raise SystemExit("a first-run artifact exists; the cohort has been scored and cannot "
                             "be reissued")
        previous = {"created_at": prior.get("created_at"),
                    "gold_digest": prior.get("gold_digest"),
                    "code_commit": prior.get("code_commit")}
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise SystemExit("tracked working tree is dirty; commit the frozen inputs first:\n" + dirty)
    protocol = _load("fixtures/answer_semantics/holdout_protocol.json")
    plan = _load("fixtures/answer_semantics/holdout_plan.json")
    questions = _load("fixtures/answer_semantics/holdout_questions.json")
    facts = _load("fixtures/answer_semantics/holdout_facts.json")
    ledger = _load("fixtures/answer_semantics/holdout_ledger.json")
    corpus = _load("fixtures/answer_semantics/holdout_corpus.json")
    manifest = _load("artifacts/answer_semantics/holdout_source_manifest.json")
    from atlas.research.answer_semantics import EVALUATION_VERSION

    payload = {
        "schema": "atlas.answer_semantics.holdout_freeze.v1",
        "status": "frozen_awaiting_first_run",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": ("Preregistration of the first prospective answer-semantics evaluation. Written "
                    "after the gold commit and before either resolver is run on the cohort."),
        "protocol_version": protocol["version"],
        "evaluation_version": EVALUATION_VERSION,
        "code_commit": _git("rev-parse", "HEAD"),
        "selection": {
            "plan_commitment": plan["commitment"],
            "accessions": [item["accession"] for item in plan["filings"]],
            "seed": plan["seed"],
            "selection_rule": plan["selection_rule"],
            "changed_after_freeze": False,
        },
        "counts": _counts(),
        "source_bytes": {
            "filings": len(manifest["filings"]),
            "sha256": {item["accession"]: item["document_sha256"] for item in manifest["filings"]},
            "xbrl_digest": manifest["xbrl"]["digest"],
        },
        "inputs": holdout.input_hashes(),
        "code": holdout.code_hashes(),
        "gold_digest": holdout.gold_digest(questions, facts, ledger, corpus, protocol),
        "metrics": protocol["metrics"],
        "analysis_plan": protocol["analysis_plan"],
        "reviewer_limitations": protocol["reviewer_limitations"],
        "reissue": {"previous": previous, "reason": reissue,
                     "statement": ("Reissued before any score existed: the superseded record was "
                                   "aborted during ingestion and neither resolver had run on a "
                                   "holdout question.")} if reissue else None,
        "freeze_rules": {
            "one_run": "the first scored run is executed once on this cohort; its artifact is preserved",
            "no_tuning": "no resolver change, question change or alias addition may follow the run and still be called a holdout",
            "post_freeze_change": "any change to a frozen input or to resolution code makes this cohort a development set",
            "verification": "scripts/answer_semantics_holdout_evaluate.py calls --check and refuses to run on drift",
        },
    }
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {FREEZE}")
    print(f"gold_digest {payload['gold_digest']}")
    print(json.dumps(payload["counts"], indent=1))
    return 0


def check() -> int:
    freeze = json.loads(FREEZE.read_text())
    problems: list[str] = []
    if freeze.get("status") not in {"frozen_awaiting_first_run", "first_run_completed"}:
        problems.append(f"unexpected freeze status {freeze.get('status')!r}")
    recorded_inputs = freeze.get("inputs") or {}
    current_inputs = holdout.input_hashes()
    for relative in sorted(set(recorded_inputs) | set(current_inputs)):
        if recorded_inputs.get(relative) != current_inputs.get(relative):
            problems.append(f"frozen input changed: {relative}")
    recorded_code = freeze.get("code") or {}
    current_code = holdout.code_hashes()
    for relative in sorted(set(recorded_code) | set(current_code)):
        if recorded_code.get(relative) != current_code.get(relative):
            problems.append(f"resolution code changed: {relative}")
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        problems.append("tracked working tree is dirty:\n" + dirty)
    head = _git("rev-parse", "HEAD")
    for relative in sorted(recorded_inputs):
        try:
            committed = _git("rev-parse", f"HEAD:{relative}")
        except SystemExit:
            problems.append(f"frozen input is not committed at HEAD: {relative}")
            continue
        working = _git("hash-object", relative)
        if committed != working:
            problems.append(f"frozen input differs from its committed blob: {relative}")
    print(f"freeze status {freeze.get('status')} gold_digest {freeze.get('gold_digest')}")
    print(f"freeze code_commit {freeze.get('code_commit')} head {head}")
    if problems:
        for problem in problems:
            print(f"[error] {problem}")
        print(f"freeze check FAILED with {len(problems)} problem(s)")
        return 1
    print("freeze check OK: frozen inputs, committed blobs and resolution code all match")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="write the preregistration")
    group.add_argument("--reissue", metavar="REASON",
                       help="supersede an unscored preregistration, recording why")
    group.add_argument("--check", action="store_true", help="verify the preregistration")
    args = parser.parse_args(argv)
    if args.reissue:
        return write(reissue=args.reissue)
    return write() if args.write else check()


if __name__ == "__main__":
    raise SystemExit(main())
