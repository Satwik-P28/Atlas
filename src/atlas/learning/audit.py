"""Model auditor.

The auditor reports named findings with evidence and limitations. It deliberately
does not emit an overall credibility score: a single number would hide which
assumption failed and would invite users to compare incomparable studies.
"""

from __future__ import annotations

from typing import Any


def _finding(code: str, severity: str, summary: str, *, evidence: dict[str, Any] | None = None,
             limitation: str | None = None) -> dict[str, Any]:
    return {"finding_key": code, "severity": severity, "summary": summary,
            "evidence": evidence or {}, "limitation": limitation}


def audit_result(result: dict[str, Any], *, feature_correlation: float,
                 train_rows: int, test_rows: int, selected_model: str,
                 data_class: str, rights: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    metrics = result.get("test", {})
    baseline = result.get("baseline", {})
    split = result.get("split", {})
    findings.append(_finding(
        "chronological_partitions", "info" if split.get("test_used_for_selection") is False else "error",
        "The final test interval was not used to select the model or calibrator.",
        evidence={"train_end": split.get("train", {}).get("end"),
                  "test_start": split.get("test", {}).get("start"),
                  "embargo_sessions": split.get("embargo"),
                  "test_used_for_selection": split.get("test_used_for_selection")},
        limitation="Chronological separation does not remove regime dependence.",
    ))
    if test_rows < 200:
        findings.append(_finding(
            "small_test_sample", "warning",
            f"The untouched test interval has only {test_rows} forecast rows; confidence intervals will be wide.",
            evidence={"test_rows": test_rows},
            limitation="Rows from the same session are cross-sectionally dependent.",
        ))
    if metrics.get("prevalence") is not None and min(metrics["prevalence"], 1 - metrics["prevalence"]) < 0.25:
        findings.append(_finding(
            "class_imbalance", "warning",
            "One outcome class is below 25% prevalence; accuracy alone is misleading.",
            evidence={"prevalence": metrics["prevalence"]},
            limitation="Brier and log loss are still defined but less stable.",
        ))
    if feature_correlation > 0.95:
        findings.append(_finding(
            "collinear_features", "warning",
            "At least two features have absolute correlation above 0.95.",
            evidence={"max_abs_correlation": feature_correlation},
            limitation="Coefficient signs may be unstable even when prediction is stable.",
        ))
    if selected_model == "climatology":
        findings.append(_finding(
            "no_learned_edge", "warning",
            "The climatology baseline won validation; the sophisticated models did not justify themselves.",
            evidence={"selected_model": selected_model,
                      "validation_brier": result.get("selection", {}).get("brier")},
            limitation="A different feature set or regime could still contain signal.",
        ))
    skill = metrics.get("brier_skill_vs_climatology")
    interval = result.get("uncertainty", {}).get("paired_brier_difference")
    if skill is None or skill <= 0:
        findings.append(_finding(
            "test_skill_not_supported", "warning",
            "The selected model did not improve test Brier score over climatology.",
            evidence={"brier_skill": skill, "test_brier": metrics.get("brier"),
                      "baseline_brier": baseline.get("brier")},
            limitation="A negative result on this dataset is not proof that the feature family is useless.",
        ))
    elif interval and interval.get("low") is not None and interval["low"] <= 0:
        findings.append(_finding(
            "improvement_interval_includes_zero", "warning",
            "The paired block-bootstrap interval for the Brier improvement includes zero.",
            evidence=interval,
            limitation="The bootstrap cannot repair a biased or non-representative panel.",
        ))
    else:
        findings.append(_finding(
            "test_improvement_supported", "info",
            "The test Brier improvement is positive and its paired interval excludes zero.",
            evidence={"brier_skill": skill, "interval": interval},
            limitation="This is forecast accuracy evidence, not proof of economic value.",
        ))
    findings.append(_finding(
        "data_vintage", "warning" if data_class != "point_in_time_verified" else "info",
        "The panel is observed/reconstructed, not a point-in-time verified historical vintage.",
        evidence={"data_class": data_class, "rights": rights},
        limitation="Provider downloads do not prove what was displayed at the historical instant.",
    ))
    if rights == "restricted":
        findings.append(_finding(
            "redistribution_restricted", "warning",
            "Source rights are restricted; artifacts may be retained locally but not redistributed.",
            evidence={"rights": rights},
            limitation="Users must confirm their own entitlement before exporting data.",
        ))
    findings.append(_finding(
        "economic_value_not_established", "warning",
        "Forecast accuracy is not the same as a profitable trading rule after costs.",
        evidence={"portfolio_experiment": result.get("portfolio_experiment")},
        limitation="Phase 6 demonstrates the conversion path; it does not claim alpha.",
    ))
    findings.append(_finding(
        "reproducibility_scope", "info",
        "The model artifact, feature schema, split, seed and source hash are retained.",
        evidence={"artifact_fingerprint": result.get("model", {}).get("fingerprint"),
                  "panel_hash": result.get("dataset", {}).get("content_hash")},
        limitation="Exact vendor bytes are not committed when rights are restricted.",
    ))
    return {
        "schema": "atlas.learning.audit.v1",
        "findings": findings,
        "counts": {
            "error": sum(1 for item in findings if item["severity"] == "error"),
            "warning": sum(1 for item in findings if item["severity"] == "warning"),
            "info": sum(1 for item in findings if item["severity"] == "info"),
        },
        "overall_score": None,
        "note": "No aggregate credibility score is produced; read each finding and its limitation.",
    }


__all__ = ["audit_result"]
