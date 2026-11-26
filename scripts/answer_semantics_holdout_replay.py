"""Replay the frozen holdout run offline and compare it with the preserved first-run artifact.

Replay is an audit of the machinery, not a second experiment: it must not be used to replace,
improve or re-report the first run. It re-parses the archived bytes (verifying every SHA-256
against the source manifest), re-runs both resolvers on the same frozen questions and compares
every per-question classification and answer field with the artifact. Timing is recorded
separately because it varies by machine.

Replay is only meaningful against the code that produced the artifact. When the working tree's
resolution code no longer matches the preregistration's recorded hashes, replay refuses (exit 3)
unless ``--live`` is given: after hardening, the live resolver is a *different system*, and its
output on this cohort is a post-holdout development measurement, not a replay of the first run.
The historical experiment is audited by ``answer_semantics_holdout_archive.py`` instead.

Exit codes: 0 identical classifications; 1 differences; 2 missing inputs; 3 code drift.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research import answer_semantics, holdout  # noqa: E402

FIELDS = ("status", "outcome", "correct", "value_ok", "period_ok", "unit_ok", "numerical_ok",
          "citation_ok", "source_ok", "header_confirmed", "reason")


def _comparable(item: dict[str, Any]) -> dict[str, Any]:
    digest = {key: item.get(key) for key in FIELDS}
    response = item.get("response") or {}
    digest["value_display"] = response.get("value_display")
    digest["value_economic"] = response.get("value_economic")
    digest["accession"] = response.get("accession")
    digest["period"] = response.get("period")
    digest["scale"] = response.get("scale")
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artifact", default=str(holdout.OUTPUT_PATH))
    #: Replay is an audit, and its timing changes on every machine. Writing to the gitignored
    #: workspace by default keeps a replay run from dirtying the tracked first-run evidence;
    #: pass --out artifacts/... deliberately to publish a new record.
    parser.add_argument("--out", default=str(ROOT / "var" / "answer_semantics" / "holdout"
                                              / "replay.json"))
    parser.add_argument("--work", default=str(ROOT / "var" / "answer_semantics" / "holdout"
                                              / "replay_run.json"))
    parser.add_argument("--live", action="store_true",
                        help="replay the working tree's resolver even though it differs from the "
                             "frozen one (a development measurement, not the first run)")
    args = parser.parse_args(argv)
    artifact = Path(args.artifact)
    if not artifact.exists():
        print(f"no first-run artifact at {artifact}", file=sys.stderr)
        return 2
    if not holdout.SNAPSHOTS.exists():
        print(f"archived filings are not present at {holdout.SNAPSHOTS}; replay needs the "
              "gitignored snapshots", file=sys.stderr)
        return 2
    freeze = json.loads(holdout.FREEZE_PATH.read_text())
    drifted = sorted(path for path, digest in holdout.code_hashes().items()
                     if freeze["code"].get(path) not in {None, digest})
    if drifted and not args.live:
        print("the working tree's resolution code differs from the frozen resolver "
              f"({len(drifted)} file(s)); replay this artifact only with --live, and label the "
              "result a post-holdout development run", file=sys.stderr)
        return 3
    recorded = json.loads(artifact.read_text())
    started = time.perf_counter()
    replayed = answer_semantics.run(
        output=Path(args.work), db_path=holdout.DB_PATH, snapshots=holdout.SNAPSHOTS,
        questions_path=holdout.QUESTIONS_PATH, manifest_path=holdout.MANIFEST_PATH,
        facts_path=holdout.FACTS_PATH, corpus_path=holdout.CORPUS_PATH)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    left = {(item["id"], item["runner"]): _comparable(item) for item in recorded["results"]}
    right = {(item["id"], item["runner"]): _comparable(item) for item in replayed["results"]}
    mismatches = []
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            mismatches.append({"question": key[0], "runner": key[1],
                               "recorded": left.get(key), "replayed": right.get(key)})
    def _without_latency(metrics: dict[str, Any]) -> dict[str, Any]:
        return {runner: {key: value for key, value in arm.items() if key != "latency_ms"}
                for runner, arm in metrics.items()}

    metrics_match = _without_latency(recorded["metrics"]) == _without_latency(replayed["metrics"])
    latency = {
        runner: {"recorded": recorded["metrics"][runner].get("latency_ms"),
                 "replayed": replayed["metrics"][runner].get("latency_ms")}
        for runner in recorded["metrics"]
    }
    payload = {
        "schema": "atlas.answer_semantics.holdout_replay.v1",
        "artifact": str(artifact.relative_to(ROOT)),
        "artifact_sha256": holdout.file_digest(artifact),
        "questions_compared": len(left),
        "classifications_identical": not mismatches,
        "metric_comparison_identical": metrics_match,
        "latency_comparison": latency,
        "mismatches": mismatches,
        "replay_elapsed_ms": elapsed_ms,
        "recorded_wall_ms": (recorded.get("run") or {}).get("wall_ms"),
        "timing_note": "timing differs by environment; only classifications are the claim",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: payload[key] for key in
                      ("questions_compared", "classifications_identical",
                       "metric_comparison_identical", "replay_elapsed_ms")}, indent=1))
    if mismatches:
        print(f"{len(mismatches)} mismatching result(s); first: {mismatches[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
