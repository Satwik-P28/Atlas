"""Recompute the post-run adjudication sensitivity table from the preserved first run.

The adjudications in ``fixtures/answer_semantics/holdout_adjudications.json`` are append-only and
never alter the frozen labels. This script turns each one into an explicit counterfactual so a
reader can see how much of a conclusion depends on a contested label: it removes or reclassifies
only for the purposes of the sensitivity table, and writes the result next to the artifact.

Usage::

    python scripts/answer_semantics_holdout_adjudicate.py --write
    python scripts/answer_semantics_holdout_adjudicate.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research import holdout  # noqa: E402

ADJUDICATIONS_PATH = holdout.FIXTURES / "holdout_adjudications.json"
OUTPUT_PATH = holdout.ARTIFACTS / "holdout_adjudication_sensitivity.json"


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 4)


def sensitivity() -> dict[str, Any]:
    artifact = json.loads(holdout.OUTPUT_PATH.read_text())
    record = json.loads(ADJUDICATIONS_PATH.read_text())
    results = artifact["results"]
    by_id = {(item["id"], item["runner"]): item for item in results}
    answerable = sorted({item["id"] for item in results if item["gold_class"] == "xbrl_verified"})
    adjudications = {item["id"]: item for item in record["adjudications"]}

    rows: list[dict[str, Any]] = []
    for variant in record["sensitivity_variants"]:
        dropped: set[str] = set()
        upgraded: set[str] = set()
        for adjudication_id in variant["adjudications"]:
            entry = adjudications[adjudication_id]
            if entry["effect"] == "exclude_from_answerable":
                dropped.add(entry["question_id"])
            elif entry["effect"] == "accept_citation":
                upgraded.add(entry["question_id"])
        denominators = [qid for qid in answerable if qid not in dropped]
        row: dict[str, Any] = {"variant": variant["id"], "answerable": len(denominators),
                               "adjudications": variant["adjudications"]}
        for runner in ("baseline", "geometry"):
            correct = 0
            false = 0
            for qid in denominators:
                item = by_id[(qid, runner)]
                if item["status"] == "correct" or (qid in upgraded
                                                   and item["status"] == "citation_failure"):
                    correct += 1
                if item["status"] == "false_answer":
                    false += 1
            row[runner] = {"correct": correct, "false": false,
                           "exact_answer_rate": _rate(correct, len(denominators))}
        rows.append(row)
    return {
        "schema": "atlas.answer_semantics.holdout_adjudication_sensitivity.v1",
        "artifact": str(holdout.OUTPUT_PATH.relative_to(ROOT)),
        "artifact_sha256": holdout.file_digest(holdout.OUTPUT_PATH),
        "adjudications": str(ADJUDICATIONS_PATH.relative_to(ROOT)),
        "adjudications_sha256": holdout.file_digest(ADJUDICATIONS_PATH),
        "headline_unchanged": True,
        "variants": rows,
        "note": ("Counterfactual arithmetic over the preserved run. No gold label, question or "
                 "historical artifact was modified."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    payload = sensitivity()
    if args.write:
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"wrote {OUTPUT_PATH}")
    if args.check or not args.write:
        if not OUTPUT_PATH.exists():
            print(f"no sensitivity record at {OUTPUT_PATH}", file=sys.stderr)
            return 2
        recorded = json.loads(OUTPUT_PATH.read_text())
        if recorded.get("variants") != payload["variants"]:
            print("sensitivity record does not match the preserved run", file=sys.stderr)
            return 1
        print("adjudication sensitivity verified")
    for row in payload["variants"]:
        print(f"  {row['variant']:22s} n={row['answerable']} "
              f"baseline {row['baseline']['correct']} ({row['baseline']['exact_answer_rate']}) "
              f"geometry {row['geometry']['correct']} ({row['geometry']['exact_answer_rate']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
