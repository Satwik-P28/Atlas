# Phase 9.6.3 — Independent evaluation

Runner: `scripts/phase9_6_3_evaluate.py`; artifact `artifacts/phase9_6_3_evaluation.json`
(sanitized). Historical 9.6.0/9.6.1/9.6.2 artifacts are unchanged.

## Fixed classification of all 112 eligible questions

| Category | Eligible | Attempted | Unsupported |
| --- | --- | --- | --- |
| narrative | 34 | 0 | 34 |
| yes/no | 27 | 0 | 27 |
| numeric direct | 19 | 6 | 13 |
| numeric arithmetic | 32 | 0 | 32 (operand mapping not evaluated) |

## Metrics

| Metric | Value |
| --- | --- |
| concept resolution (of attempted) | 0.3333 (2/6) |
| cell localization (of resolved) | 0.5000 (1/2) |
| answer correctness among answered | 0.5000 (1/2) |
| correct over all attempted | 0.1667 |
| citation integrity | 1.0 |
| abstention precision (constructed negatives) | 0.9167 |
| abstention recall | 1.0 |
| false assertion rate | 0.0833 |
| value coincidence (old, weak metric) | 0.1667 |

The 9.6.2 evaluator would have credited the same 1 case as "localized" through value coincidence;
9.6.3 requires the concept first. Arithmetic questions are counted as unsupported rather than
being scored as failed lookups.

## Gates

Concept resolution (≥0.30) **passed at 0.333**. Cell localization (≥0.20) **passed at 0.50** but on
an n of 2 and must not be read as capability. Answer correctness (≥0.80) **failed at 0.50**.
Citation integrity passed. Abstention precision passed. False assertions were 0.0833, within the
preregistered 0.10 bound, so that gate passed despite three false assertions.

## Limitations

* No XBRL, so concept identity is not independently confirmed.
* PDF annotation spans cannot be aligned to SEC HTML; table-level annotation alignment is not
  evaluated.
* Negatives are deterministic constructions, not a human-reviewed holdout.
* Wilson intervals are in the artifact; with n=2 they are uninformative.
