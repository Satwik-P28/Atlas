"""Score the hardened resolver on the exposed twelve-issuer cohort — as development, not as a test.

The cohort stopped being out-of-sample the moment its first run was scored and its failures were
read. Re-running it is legitimate development work (it is the regression suite for real filings),
but it is **not** a new prospective evaluation and must never be reported as one. This script makes
that distinction part of the artifact: every output carries an explicit label, the commit that
produced it, and a digest of the preserved first run it must not be confused with.

Usage::

    python scripts/answer_semantics_postholdout_dev.py --iteration 1
    python scripts/answer_semantics_postholdout_dev.py --iteration 2 --note "column groups"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research import answer_semantics, holdout  # noqa: E402

DEV_LABEL = "post_holdout_development"


def _git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--note", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    destination = Path(args.out) if args.out else (
        holdout.ARTIFACTS / f"holdout_development_iter{args.iteration}.json")
    if destination.resolve() == holdout.OUTPUT_PATH.resolve():
        print("refusing to overwrite the preserved first-run artifact", file=sys.stderr)
        return 2
    started = time.perf_counter()
    report = answer_semantics.run(
        output=destination, db_path=holdout.DB_PATH, snapshots=holdout.SNAPSHOTS,
        questions_path=holdout.QUESTIONS_PATH, manifest_path=holdout.MANIFEST_PATH,
        facts_path=holdout.FACTS_PATH, corpus_path=holdout.CORPUS_PATH)
    report["evaluation_label"] = DEV_LABEL
    report["label_explanation"] = (
        "The twelve issuers were used for the first prospective run; this is a development "
        "regression on exposed data, not an independent confirmation.")
    report["iteration"] = args.iteration
    report["note"] = args.note
    report["code_commit"] = _git_head()
    report["first_run_artifact_sha256"] = holdout.file_digest(holdout.OUTPUT_PATH)
    report["wall_ms"] = round((time.perf_counter() - started) * 1000, 3)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for runner in ("baseline", "geometry"):
        arm = report["metrics"][runner]
        print(f"{runner:9s} correct {arm['correct']}/{arm['answerable']} "
              f"({arm['exact_answer_rate']}) answered {arm['answered']} "
              f"false {arm['false_answers']} citation {arm['citation_failures']} "
              f"answerable abstentions {arm['answerable_abstentions']}")
    print(f"wrote {destination} ({report['wall_ms'] / 1000:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
