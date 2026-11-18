"""Render every table in the study report from the generated JSON. Do not hand-edit tables.

Run: ``.venv/bin/python scripts/research/rtds_tables.py``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "artifacts" / "research" / "rtds"


def pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{100.0 * value:.{digits}f}%"


def interval(block: dict[str, Any] | None) -> str:
    if not block or block.get("lower") is None:
        return "n/a"
    return f"[{100.0 * block['lower']:.1f}%, {100.0 * block['upper']:.1f}%]"


def number(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if value != 0 and (abs(value) < 1e-3 or abs(value) >= 1e5):
        return f"{value:.{digits-1}e}"
    return f"{value:.{digits}f}"


def table(header: Iterable[str], rows: Iterable[Iterable[str]]) -> list[str]:
    header = list(header)
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def dataset_section(dataset: dict[str, Any], previous: dict[str, Any] | None) -> list[str]:
    lines = ["## Data", ""]
    header = ["cohort", "frequency", "series", "vintage responses", "train", "pilot", "test",
              "holdout"]
    rows = []
    for cohort in dataset["cohorts"]:
        key = cohort["cohort"]
        counts = {split: sum(1 for event in cohort["events"] if event["split"] == split)
                  for split in ("train", "pilot", "test", "holdout")}
        rows.append([key, cohort["frequency"], ", ".join(cohort["series"]),
                     str(cohort["manifest_counts"]["files"]), str(counts["train"]),
                     str(counts["pilot"]), str(counts["test"]), str(counts["holdout"])])
    lines += table(header, rows)
    lines.append("")
    lines.append("Horizon rule: " + dataset["horizon_rule"] + ". A vintage date is a release date "
                 "and is treated as available at 23:59:59 UTC; no intraday claim is made.")
    lines.append("")
    if previous is not None:
        lines.append("**Audit-vintage change from the superseded 400/366-day horizons.**")
        lines.append("")
        header = ["cohort", "paired events", "audit vintage unchanged", "audit vintage changed",
                  "median horizon (days)"]
        rows = []
        for new, old in zip(dataset["cohorts"], previous["cohorts"]):
            previous_by_period = {event["period"]: event for event in old["events"]}
            same = changed = 0
            for event in new["events"]:
                before = previous_by_period.get(event["period"])
                if before is None:
                    continue
                if before["audit_vintage"] == event["audit_vintage"]:
                    same += 1
                else:
                    changed += 1
            horizons = sorted(event["horizon_days_actual"] for event in new["events"])
            median = horizons[len(horizons) // 2] if horizons else 0
            rows.append([new["cohort"], str(same + changed), str(same), str(changed), str(median)])
        lines += table(header, rows)
        lines.append("")
    return lines


def headline_section(results: dict[str, Any], previous: dict[str, Any] | None) -> list[str]:
    lines = ["## Materiality and certification (confirmatory test split)", ""]
    header = ["cohort", "events", "material (95% cluster CI)", "certified immaterial",
              "certified material", "unknown", "false immaterial", "false material"]
    rows = []
    for cohort in results["cohorts"]:
        test = cohort["test"]
        materiality = test["materiality"]
        certification = test["certification"]
        rows.append([
            cohort["cohort"], str(test["events"]),
            f"{pct(materiality['share'])} {interval(materiality['interval'])}",
            f"{certification['immaterial']} ({pct(certification['immaterial_share'])})",
            f"{certification['material']} ({pct(certification['material_share'])})",
            f"{certification['unknown']} ({pct(certification['unknown_share'])})",
            str(certification["false_immaterial"]), str(certification["false_material"])])
    lines += table(header, rows)
    lines.append("")
    lines.append("`certified material` is established by a feasible descent (a lower bound on "
                 "regret), never by an upper bound above the threshold. `unknown` is the honest "
                 "third category: neither claim is justified.")
    lines.append("")

    lines.append("**Untouched later period (2024-07-01 .. 2025-06-30), first computed here.**")
    lines.append("")
    header = ["cohort", "events", "material", "certified immaterial", "certified material",
              "unknown"]
    rows = []
    for cohort in results["cohorts"]:
        holdout = cohort["holdout"]
        if not holdout.get("events"):
            rows.append([cohort["cohort"], "0", "n/a", "n/a", "n/a", "n/a"])
            continue
        rows.append([cohort["cohort"], str(holdout["events"]),
                     pct(holdout["materiality"]["share"]),
                     pct(holdout["certification"]["immaterial_share"]),
                     pct(holdout["certification"]["material_share"]),
                     pct(holdout["certification"]["unknown_share"])])
    lines += table(header, rows)
    lines.append("")
    if previous is not None:
        lines.append("**Superseded versus corrected (test split).**")
        lines.append("")
        header = ["cohort", "materiality (v1)", "materiality (v2)",
                  "certified immaterial (v1)", "certified immaterial (v2)",
                  "CRI-vs-KKT agreement (v1)", "CRI-vs-KKT agreement (v2)"]
        rows = []
        for new, old in zip(results["cohorts"], previous["cohorts"]):
            old_cert = old["certification"]["share_certified_immaterial"]
            old_agree = old.get("agreement", {})
            new_agree = new["agreement"]
            rows.append([
                new["cohort"], pct(old["materiality"]["share"]),
                pct(new["test"]["materiality"]["share"]), pct(old_cert),
                pct(new["test"]["certification"]["immaterial_share"]),
                f"{old_agree.get('certified_and_stable', 0)}/"
                f"{old_agree.get('certified_not_stable', 0)}/"
                f"{old_agree.get('stable_not_certified', 0)}",
                f"{new_agree['certified_and_stable']}/{new_agree['certified_not_stable']}/"
                f"{new_agree['stable_not_certified']}"])
        lines += table(header, rows)
        lines.append("")
        lines.append("The v1 columns are not comparable on the merits: they describe the program "
                     "`z_A - 2 z_D`, which is not the model the protocol defines. Agreement cells "
                     "are `certified and KKT-stable / certified but not stable / stable but not "
                     "certified`.")
        lines.append("")
    return lines


def certificate_section(results: dict[str, Any]) -> list[str]:
    lines = ["## Certificate coverage, abstention and soundness", ""]
    header = ["cohort", "method", "immaterial certificates", "material certificates",
              "abstentions", "decisions certified", "false immaterial",
              "immaterial events covered"]
    rows = []
    for cohort in results["cohorts"]:
        for key, block in cohort["certificates"].items():
            rows.append([
                cohort["cohort"], block["method"], str(block["certified_immaterial"]),
                str(block["certified_material"]), str(block["abstentions"]),
                pct(block["decisions_certified"]), str(block["false_immaterial_certificates"]),
                f"{block['certified_immaterial']}/{block['immaterial_events']}"])
    lines += table(header, rows)
    lines.append("")
    lines.append("A method that only produces an upper bound can certify immateriality and nothing "
                 "else; its `material certificates` column is zero by construction, so its old "
                 "`accuracy` figure (which counted `bound > tau` as a materiality claim) has been "
                 "withdrawn.")
    lines.append("")
    lines.append("**Ranking heuristics (predictions, not certificates).**")
    lines.append("")
    header = ["cohort", "heuristic", "AUC"]
    rows = []
    for cohort in results["cohorts"]:
        for key, block in cohort["heuristics"].items():
            rows.append([cohort["cohort"], block["heuristic"], number(block.get("auc"))])
    lines += table(header, rows)
    lines.append("")
    return lines


def agreement_section(results: dict[str, Any]) -> list[str]:
    lines = ["## CRI certificates versus the classical active-set test", ""]
    header = ["cohort", "certified and KKT-stable", "certified but not stable",
              "stable but not certified", "test events"]
    rows = []
    for cohort in results["cohorts"]:
        block = cohort["agreement"]
        rows.append([cohort["cohort"], str(block["certified_and_stable"]),
                     str(block["certified_not_stable"]), str(block["stable_not_certified"]),
                     str(block["test_events"])])
    lines += table(header, rows)
    lines.append("")
    lines.append("**Bound tightness.**")
    lines.append("")
    header = ["cohort", "median bound, material", "median bound, immaterial",
              "median bound / regret (material)", "median lower bound, material",
              "median lower / regret (material)"]
    rows = []
    for cohort in results["cohorts"]:
        tight = cohort["test"]["tightness"]
        rows.append([cohort["cohort"], number(tight["median_bound_material"]),
                     number(tight["median_bound_immaterial"]),
                     number(tight["median_bound_over_regret_material"]),
                     number(tight["median_lower_bound_material"]),
                     number(tight["median_lower_over_regret_material"])])
    lines += table(header, rows)
    lines.append("")
    return lines


def prediction_section(results: dict[str, Any]) -> list[str]:
    lines = ["## What predicts materiality", ""]
    header = ["cohort", "feature group", "features", "AUC", "95% cluster CI", "radius used",
              "median feature cost (ms)", "KKT checks per event"]
    rows = []
    for cohort in results["cohorts"]:
        for key, block in cohort["prediction"]["groups"].items():
            rows.append([cohort["cohort"], key, ", ".join(block["features"]),
                         number(block.get("auc")), interval(block.get("auc_interval")),
                         "yes" if block["uses_stability_radius"] else "no",
                         number(block.get("median_total_ms_per_event"), 2),
                         number(block.get("kkt_evaluations_per_event"), 1)])
    lines += table(header, rows)
    lines.append("")
    lines.append("The directional stability radius is a diagnostic, not free metadata: it runs a "
                 "bracketing search of multiplier recoveries and KKT checks along the observed "
                 "revision, and its cost is charged to the group that uses it.")
    lines.append("")
    return lines


def cost_section(results: dict[str, Any]) -> list[str]:
    lines = ["## Computational cost and stored state", ""]
    header = ["cohort", "decision", "certificate", "compile", "repair", "active-set",
              "warm re-solve", "internal re-solve", "OSQP re-solve", "radius search"]
    rows = []
    for cohort in results["cohorts"]:
        timing = cohort["timing_ms"]
        rows.append([cohort["cohort"]] + [
            number(timing[name]["median"], 2) for name in
            ("decision_ms", "certificate_ms", "compile_ms", "repair_ms", "active_set_ms",
             "warm_ms", "internal_ms", "external_ms", "radius_ms")])
    lines += table(header, rows)
    lines.append("")
    lines.append("**Stored state per decision (bytes).**")
    lines.append("")
    header = ["cohort", "sufficient audit record", "shared structure (once)",
              "amortized shared", "record + amortized", "audit-vintage cost vector only",
              "cost vector + amortized", "full serialised problem"]
    rows = []
    for cohort in results["cohorts"]:
        storage = cohort["storage"]
        rows.append([
            cohort["cohort"], number(storage["record_bytes"]["median_bytes"], 0),
            number(storage["shared_bytes"]["value"], 0),
            number(storage["amortized_shared_bytes_per_decision"]["value"], 1),
            number(storage["record_plus_amortized_shared"]["value"], 1),
            number(storage["cost_only_bytes"]["median_bytes"], 0),
            number(storage["cost_only_plus_amortized_shared"]["value"], 1),
            number(storage["problem_bytes"]["median_bytes"], 0)])
    lines += table(header, rows)
    lines.append("")
    lines.append("The record carries the recorded weights, the recorded multipliers and the "
                 "decision-time linear costs; the quadratic matrix, bounds and constraint rows are "
                 "shared and stored once. `cost vector only` is what a re-solve needs per decision "
                 "once the same structure is shared.")
    lines.append("")
    return lines


def sensitivity_section(results: dict[str, Any]) -> list[str]:
    lines = ["## Sensitivity to the risk weight and the materiality threshold", ""]
    header = ["cohort", "risk weight rho", "events", "material tau=1e-2", "tau=1e-3", "tau=1e-4",
              "certified immaterial tau=1e-3"]
    rows = []
    for key, grid in results["sensitivity"].items():
        for label, block in grid.items():
            rows.append([key, label.replace("rho=", ""), str(block["events"]),
                         pct(block["materiality"]["tau=0.01"]),
                         pct(block["materiality"]["tau=0.001"]),
                         pct(block["materiality"]["tau=0.0001"]),
                         pct(block["certified_immaterial"]["tau=0.001"])])
    lines += table(header, rows)
    lines.append("")
    return lines


def attribution_section(comparison: dict[str, Any] | None) -> list[str]:
    if not comparison:
        return []
    lines = ["## Attribution: what the correction changed, and why", ""]
    header = ["cohort", "paired test events", "audit vintage changed", "audit growth changed",
              "material: v1", "material: mapping fixed, old horizon", "material: v2",
              "certified: v1", "certified: mapping fixed", "certified: v2"]
    rows = []
    for cohort in comparison["cohorts"]:
        arms = cohort["arms"]
        events = {name: block["events"] for name, block in arms.items()}
        rows.append([
            cohort["cohort"], str(cohort["paired_test_events"]),
            str(cohort["audit_vintage_changed"]),
            str(cohort["audit_growth_coefficients_changed"]),
            f"{arms['v1']['material']}/{events['v1']}",
            f"{arms['mapping_fixed_old_horizon']['material']}/"
            f"{events['mapping_fixed_old_horizon']}",
            f"{arms['v2']['material']}/{events['v2']}",
            f"{arms['v1']['certified']}/{events['v1']}",
            f"{arms['mapping_fixed_old_horizon']['certified']}/"
            f"{events['mapping_fixed_old_horizon']}",
            f"{arms['v2']['certified']}/{events['v2']}"])
    lines += table(header, rows)
    lines.append("")
    lines.append("The middle arm isolates the sign error: same audit vintages as the superseded "
                 "study, documented cost convention. The difference between the middle and last "
                 "columns is the calendar-horizon repair.")
    lines.append("")
    return lines


def main() -> None:
    results = json.loads((DATA / "results.json").read_text())
    dataset = json.loads((DATA / "dataset.json").read_text())
    previous_path = DATA / "superseded" / "results_v1.json"
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else None
    previous_dataset_path = DATA / "superseded" / "dataset_v1.json"
    previous_dataset = (json.loads(previous_dataset_path.read_text())
                        if previous_dataset_path.exists() else None)

    lines = ["# Generated tables", "",
             "Produced by `scripts/research/rtds_tables.py` from `results.json` and `dataset.json`. "
             "Do not hand-edit.", "",
             "Convention: " + results["convention"]["invariant"] + ".", ""]
    lines += dataset_section(dataset, previous_dataset)
    lines += headline_section(results, previous)
    comparison_path = DATA / "comparison.json"
    lines += attribution_section(json.loads(comparison_path.read_text())
                                 if comparison_path.exists() else None)
    lines += certificate_section(results)
    lines += agreement_section(results)
    lines += prediction_section(results)
    lines += cost_section(results)
    lines += sensitivity_section(results)
    (DATA / "tables.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {DATA / 'tables.md'}")


if __name__ == "__main__":
    main()
