"""Score the existing resolver against the geometry-aware resolver on held-out filings.

Offline: it reads the database built by ``scripts/answer_semantics_corpus.py`` and the archived
filing bytes, never the network. Exit codes:

* ``0`` evaluation written;
* ``1`` a gate failed (only with ``--strict``);
* ``2`` the corpus is not built (no database or no snapshots) — the artifact records
  ``unavailable_corpus`` rather than inventing scores;
* ``3`` unexpected error.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research import answer_semantics  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXIT_GATE = 1
EXIT_UNAVAILABLE = 2
EXIT_UNEXPECTED = 3


def _summary_lines(report: dict) -> list[str]:
    lines = ["runner        answered  num%   cit%   exact%  precision  header  citfail  "
             "false  justified  unsupported  median_ms"]
    for runner, metrics in report["metrics"].items():
        lines.append(
            f"{runner:12s}  {metrics['answered']:7d}  {_fmt(metrics['numerical_accuracy']):>5s}  "
            f"{_fmt(metrics['citation_accuracy']):>5s}  {_fmt(metrics['exact_answer_rate']):>6s}  "
            f"{_fmt(metrics['answer_precision']):>9s}  {_fmt(metrics['period_header_confirmed']):>6s}  "
            f"{metrics['citation_failures']:6d}  {metrics['false_answers']:5d}  "
            f"{metrics['justified_abstentions']:9d}  "
            f"{metrics['unsupported_confident_answers']:11d}  "
            f"{_fmt(metrics['latency_ms']['median']):>9s}")
    return lines


def _fmt(value: object) -> str:
    return "n/a" if value is None else (f"{value:.4f}" if isinstance(value, float) else str(value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(answer_semantics.DEFAULT_DB))
    parser.add_argument("--snapshots", default=str(answer_semantics.DEFAULT_SNAPSHOTS))
    parser.add_argument("--questions", default=str(answer_semantics.QUESTIONS_PATH))
    parser.add_argument("--manifest", default=str(answer_semantics.MANIFEST_PATH))
    parser.add_argument("--facts", default=str(answer_semantics.FACTS_PATH))
    parser.add_argument("--out", default=str(answer_semantics.DEFAULT_OUTPUT))
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when the geometry path fails its declaration gate")
    args = parser.parse_args(argv)
    if not Path(args.db).exists() or not Path(args.snapshots).exists():
        payload = {
            "schema": "atlas.answer_semantics.evaluation.v1",
            "status": "unavailable_corpus",
            "detail": "run scripts/answer_semantics_corpus.py with ATLAS_SEC_USER_AGENT first",
            "database": args.db, "snapshots": args.snapshots,
        }
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps({"status": "unavailable_corpus", "database": args.db,
                          "snapshots": args.snapshots}))
        return EXIT_UNAVAILABLE
    try:
        report = answer_semantics.run(
            output=Path(args.out), db_path=Path(args.db), snapshots=Path(args.snapshots),
            questions_path=Path(args.questions), manifest_path=Path(args.manifest),
            facts_path=Path(args.facts))
    except Exception:  # noqa: BLE001 - a crash is reported, not hidden
        traceback.print_exc()
        return EXIT_UNEXPECTED
    print("\n".join(_summary_lines(report)))
    statuses = Counter(item["status"] for item in report["results"])
    print("statuses:", dict(sorted(statuses.items())))
    print("build_ms:", report["build_ms"])
    print("artifact:", args.out)
    if args.strict:
        geometry = report["metrics"]["geometry"]
        baseline = report["metrics"]["baseline"]
        # Integrity gates only. Coverage is reported, not required: gating on "geometry must
        # beat baseline" would invite tuning the resolver to this corpus instead of measuring it.
        checks = {
            "no_unsupported_confident_answers": geometry["unsupported_confident_answers"] == 0,
            "no_false_answers": geometry["false_answers"] == 0,
            "no_citation_failures": geometry["citation_failures"] == 0,
            "no_runner_errors": geometry["runner_errors"] == 0
            and baseline["runner_errors"] == 0,
        }
        if not all(checks.values()):
            print("gate failed:", {key: value for key, value in checks.items() if not value})
            return EXIT_GATE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
