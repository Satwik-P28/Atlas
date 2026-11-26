"""Render the prospective holdout numbers into the report, or verify them.

The tables in ``docs/ANSWER_SEMANTICS_HOLDOUT_REPORT.md`` between the generated markers are
produced from ``artifacts/answer_semantics/holdout_evaluation.json``. ``--check`` fails when the
committed report no longer matches the committed artifact, so prose cannot drift from evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research import holdout  # noqa: E402

REPORT = ROOT / "docs" / "ANSWER_SEMANTICS_HOLDOUT_REPORT.md"
BEGIN = "<!-- HOLDOUT-GENERATED:BEGIN -->"
END = "<!-- HOLDOUT-GENERATED:END -->"

#: Evidence-based note per question, written from the printed geometry and the resolver output.
NOTES = {
    "H-8230-01": "Caterpillar prints the same sales row in four column groups (consolidated, ME&T, "
                 "Financial Products, adjustments); both arms see several amounts for 2022.",
    "H-8230-02": "Same consolidating layout; the prior-year operand is equally ambiguous.",
    "H-8230-03": "'Total assets' repeats across the same four column groups.",
    "H-8230-04": "'Operating profit' repeats across the consolidating column groups.",
    "H-9617-04": "Printed row label is 'Total assets(a)' with a footnote marker; both arms returned "
                 "3,665,743 with a faithful citation, but the gold label list held only "
                 "'Total assets'. Gold transcription, not an answer error.",
    "H-0863-03": "Geometry bound 'Total assets' 2,932 from a segment/geography table instead of "
                 "the 182,103 consolidated total; the table was not recognised as a segment note.",
    "H-1439-01": "Baseline read 'Sales and marketing (1)' 8,047 as revenue (alias 'sales'); "
                 "geometry read 'Differences in timing of revenue recognition' 623 from a deferred-"
                 "revenue rollforward whose column header also names 2022.",
    "H-1439-02": "Both arms inherited the wrong revenue operand (8,047/7,682 and 623/547), so the "
                 "percentage change is computed correctly from the wrong rows.",
    "H-0727-01": "Baseline read 'Net (purchases), sales and maturities of marketable securities' "
                 "(1,651) from the 2021 column as revenue (alias 'sales' inside a cash-flow row).",
    "H-0727-02": "Prior-year revenue resolved ambiguously, so the change question cannot run.",
    "H-4489-01": "Baseline is ambiguous across Disney's revenue tables; geometry finds no candidate "
                 "row at all, i.e. the consolidated 'Total revenues' row is missed, not misread.",
    "H-4489-02": "Same missing row for both period ends.",
    "H-4489-03": "Both arms returned the 3,505 consolidated net income; gold records the 3,145 "
                 "NetIncomeLoss (attributable to Disney). Contested label: see §7.",
    "H-2927-01": "Boeing's '(Dollars in millions, except per share data)' banner is not in the "
                 "geometry scale vocabulary, so the matching rows carry no usable unit.",
    "H-2927-02": "Same unit gap for both revenue columns.",
    "H-2927-03": "Baseline read a subsidiary balance sheet ('Total assets $1,954'); geometry "
                 "refuses because nested tables produce conflicting 'Total assets' rows.",
    "H-1800-01": "Abbott's segment net-sales tables repeat the row label; baseline is ambiguous.",
    "H-1800-02": "Same ambiguity for both period ends.",
    "H-1800-03": "Abbott's 'Net Earnings' appears in several tables with different amounts; "
                 "baseline is ambiguous and geometry refuses.",
    "H-1800-04": "Baseline read 'Total current assets' 25,224 as total assets.",
    "H-8911-02": "Baseline resolved both operands to the 2022 revenue 93,512 (column labels "
                 "'2021' and '2021 (1)'), producing a 0.00% change.",
    "H-8911-03": "Value 3,826 is right; the citation names the '2021 (1)' column for a 2022 "
                 "figure, so the period attribution fails.",
    "H-0667-01": "Lowe's prints net sales in its earnings statement and again in percentage and "
                 "segment tables; baseline is ambiguous.",
    "H-0667-02": "Same ambiguity for both period ends.",
    "H-0667-03": "'Net earnings' is repeated in the earnings statement, the cash-flow statement and "
                 "the equity statement.",
    "H-0667-04": "'Operating income' row is not located by the baseline at all.",
}

GENERIC = {
    "false_answer": "Answered with an amount that is not the consolidated fact for the period.",
    "citation_failure": "Amount matches but the cited accession, row or raw text does not.",
    "resolution_failure": "Refused although the filing prints the evidence.",
    "unjustified_abstention": "Refused on evidence that exists, without a conflict.",
}


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.2f}%"


def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({100 * numerator / denominator:.1f}%)" if denominator else "n/a"


def render(report: dict, questions: list[dict]) -> str:
    metrics = report["metrics"]
    counts = report["run"]["counts"]
    analysis = report["analysis"]
    lines: list[str] = []
    lines.append("### Headline metrics (generated from the artifact)\n")
    lines.append("| metric | baseline | geometry | denominator |")
    lines.append("|---|---|---|---|")
    rows = [
        ("answered", "answered", "answerable"),
        ("combined exact-answer rate", "exact_answer_rate", "answerable"),
        ("numerical accuracy", "numerical_accuracy", "answerable"),
        ("citation accuracy", "citation_accuracy", "answered"),
        ("source (accession) accuracy", "source_accuracy", "answered"),
        ("period accuracy", "period_accuracy", "answered"),
        ("unit accuracy", "unit_accuracy", "answered"),
        ("answer precision", "answer_precision", "answered"),
        ("period-header confirmation", "period_header_confirmed", "answered"),
    ]
    for label, key, denominator in rows:
        base = metrics["baseline"][key]
        geom = metrics["geometry"][key]
        if key == "answered":
            base_text = _rate(base, metrics["baseline"]["answerable"])
            geom_text = _rate(geom, metrics["geometry"]["answerable"])
        else:
            base_text = _pct(base)
            geom_text = _pct(geom)
        lines.append(f"| {label} | {base_text} | {geom_text} | {denominator} |")
    lines.append("")
    lines.append("| outcome counts | baseline | geometry | denominator |")
    lines.append("|---|---|---|---|")
    for label, key, denominator in (
            ("correct", "correct", "answerable"),
            ("false confident answers", "false_answers", "answered"),
            ("citation failures", "citation_failures", "answered"),
            ("resolution failures", "resolution_failures", "answerable"),
            ("unsupported answers on abstention questions", "unsupported_confident_answers",
             "abstention"),
            ("justified abstentions", "justified_abstentions", "abstention"),
            ("runner errors", "runner_errors", "all results")):
        lines.append(f"| {label} | {metrics['baseline'][key]} | {metrics['geometry'][key]} | "
                     f"{denominator} |")
    lines.append("")
    lines.append("### Cohort counts (generated)\n")
    lines.append(f"- attempted: **{counts['ledger_attempted']}**")
    lines.append(f"- scored: **{counts['ledger_scored']}** "
                 f"({counts['answerable']} answerable, {counts['abstention']} abstention)")
    lines.append(f"- recorded but not scored: **{counts['ledger_not_scored']}**")
    lines.append(f"- excluded at scoring time (gold_inconsistent): "
                 f"**{metrics['geometry']['excluded_questions']}**")
    lines.append(f"- issuers: **{counts['issuers']}**, accessions: **{counts['accessions']}**")
    lines.append("")
    lines.append("### Issuer-level results (generated)\n")
    lines.append("| issuer | questions | answerable | abstention | baseline correct | "
                 "geometry correct | baseline false | geometry false |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in analysis["issuers"]:
        lines.append(f"| {row['issuer']} | {row['questions']} | {row['answerable']} | "
                     f"{row['abstention']} | {row['baseline_correct']} | {row['geometry_correct']} | "
                     f"{row['baseline_false']} | {row['geometry_false']} |")
    lines.append("")
    lines.append("### Paired comparison and cluster uncertainty (generated)\n")
    paired = analysis["paired"]
    bootstrap = analysis["cluster_bootstrap"]
    lines.append(f"- paired questions: **{paired['paired_questions']}** (all scored questions, "
                 f"including {counts['abstention']} abstention questions)")
    lines.append(f"- both correct: {paired['both_correct']}; geometry only: "
                 f"{paired['geometry_only_correct']}; baseline only: "
                 f"{paired['baseline_only_correct']}; neither: {paired['neither_correct']}")
    lines.append(f"- paired difference (geometry − baseline, denominator "
                 f"{paired['paired_questions']}): **{paired['difference_geometry_minus_baseline']:+.4f}**")
    lines.append(f"- exact sign test on discordant pairs: p = "
                 f"{paired['exact_sign_test_p_two_sided']}")
    lines.append(f"- issuer-cluster bootstrap 95% interval ({bootstrap['resamples']} resamples, "
                 f"seed {bootstrap['seed']}): **[{bootstrap['interval_95'][0]:+.4f}, "
                 f"{bootstrap['interval_95'][1]:+.4f}]**")
    lines.append("")
    lines.append("### Timing and cost (generated)\n")
    cost = analysis["cost"]
    lines.append("| measurement | baseline | geometry |")
    lines.append("|---|---|---|")
    lines.append(f"| warm mean per question | {cost['baseline_warm_mean_ms']} ms | "
                 f"{cost['geometry_warm_mean_ms']} ms |")
    lines.append(f"| warm median / p95 | {metrics['baseline']['latency_ms']['median']} / "
                 f"{metrics['baseline']['latency_ms']['p95']} ms | "
                 f"{metrics['geometry']['latency_ms']['median']} / "
                 f"{metrics['geometry']['latency_ms']['p95']} ms |")
    lines.append(f"| cold preprocessing | {cost['baseline_cold_build_ms']} ms | "
                 f"{cost['geometry_cold_build_ms']} ms |")
    lines.append(f"| amortised per question | {cost['baseline_amortised_ms_per_question']} ms | "
                 f"{cost['geometry_amortised_ms_per_question']} ms |")
    lines.append("")
    lines.append(f"Ingestion of the twelve filings (shared by both arms): "
                 f"{report['run']['ingest']['ingest_ms']} ms. Whole run: "
                 f"{report['run']['wall_ms']} ms. Process peak RSS: "
                 f"{report['run']['memory_mb']['after']} MB (from "
                 f"{report['run']['memory_mb']['before']} MB before ingestion; both arms share the "
                 f"process, so this is not a per-arm figure).")
    lines.append("")
    lines.append("### Refusal reasons (generated)\n")
    for runner, reasons in analysis["refusal_reasons"].items():
        rendered = ", ".join(f"`{reason}` ×{count}" for reason, count in reasons.items())
        lines.append(f"- {runner}: {rendered}")
    lines.append("")
    lines.append("### Every failure, with evidence (generated)\n")
    lines.append("| question | arm | status | gold | response | evidence |")
    lines.append("|---|---|---|---|---|---|")
    gold_by_id = {item["id"]: item for item in questions}
    printed = {item["id"]: (item["expect"].get("citations") or [{}])[0].get("raw")
               for item in questions}
    for failure in analysis["failures"]:
        identifier = failure["id"]
        response = failure.get("response") or {}
        value = response.get("value_economic") or response.get("value_display") or "—"
        note = NOTES.get(identifier) or GENERIC.get(failure["status"], "")
        lines.append(f"| {identifier} | {failure['runner']} | `{failure['status']}` | "
                     f"{printed.get(identifier) or 'abstain'} | {value} | {note} |")
    lines.append("")
    lines.append(f"_Generated from `{holdout.OUTPUT_PATH.relative_to(ROOT)}` "
                 f"(sha256 {holdout.file_digest(holdout.OUTPUT_PATH)[:16]}…), first run at "
                 f"{report['run']['executed_at']} against gold freeze commit "
                 f"`{report['run']['gold_freeze_commit'][:7]}`._")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report", default=str(REPORT))
    args = parser.parse_args(argv)
    if not holdout.OUTPUT_PATH.exists():
        print("no first-run artifact; nothing to render", file=sys.stderr)
        return 2
    report = json.loads(holdout.OUTPUT_PATH.read_text())
    questions = json.loads(holdout.QUESTIONS_PATH.read_text())["questions"]
    block = render(report, questions)
    path = Path(args.report)
    text = path.read_text()
    if BEGIN not in text or END not in text:
        print(f"report is missing the generated markers {BEGIN} / {END}", file=sys.stderr)
        return 2
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    updated = f"{head}{BEGIN}\n{block}\n{END}{tail}"
    if args.write:
        path.write_text(updated)
        print(f"wrote generated block into {path}")
        return 0
    if updated != text:
        print("report tables no longer match the artifact; run --write and review the diff",
              file=sys.stderr)
        return 1
    print("report tables match the committed first-run artifact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
