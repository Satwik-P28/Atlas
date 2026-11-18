# Real-world revision study (version 2, corrected)

Version 1 of this study was invalid for the model its protocol defines: the audit-time objective was
built with the wrong coefficient mapping. Version 2 repairs the design, reruns everything and reports
which conclusions survive. **[CORRECTIONS.md](CORRECTIONS.md) is the place to start** — it lists every
defect, how it was detected, the fix, the verification and the numerical impact. Version 1's outputs are
preserved unchanged under `../../artifacts/research/rtds/superseded/`.

| file | what it is |
|---|---|
| `CORRECTIONS.md` | the methodological correction log, defect by defect |
| `PREREGISTRATION.md` | the protocol; §9 separates pre-confirmatory from post-hoc amendments |
| `REPORT.md` | the paper draft: data, design, corrected results, what survived, threats |
| `NOVELTY.md` | literature positioning, updated for the corrected contribution |
| `../../artifacts/research/rtds/dataset.json` | the event archive: 408 decision/audit pairs, values, digests |
| `../../artifacts/research/rtds/results.json` | per-event results and statistics (v2) |
| `../../artifacts/research/rtds/comparison.json` | v1 vs corrected, with attribution to each defect |
| `../../artifacts/research/rtds/audit_records.json` | the sufficient minimal audit record, plus a fresh-process verification |
| `../../artifacts/research/rtds/tables.md` | every table in the report, generated from the JSON |

Scripts: `rtds_build.py` (fetch and build), `rtds_model.py` (the one cost convention, the direct audit
program, the equivalence assertion, the materiality witness), `rtds_study.py` (decisions, certificates,
witnesses, statistics), `rtds_audit_record.py` (sufficient stored state and its verification),
`rtds_compare.py` (attribution), `rtds_tables.py` (render tables). Design regressions:
`tests/test_rtds_design.py`.

Headline, corrected: across 2,347 ALFRED vintage responses and 152 confirmatory decision/audit pairs,
50.0% and 73.7% of authentic revisions move the optimal decision by more than 1e-3 objective units. A
certificate computed from the original decision proves immateriality for 44.7% and 21.1% of events
(covering 89.5% and 80.0% of the immaterial ones), never certifies a material revision as immaterial, and
selects exactly the events a classical active-set test already selects. A feasible descent supplies the
opposite direction, certifying materiality for 57 and 28 events and leaving 5.3% unknown. Revision size
does not predict materiality (AUC 0.540 and 0.425); decision geometry without a stability-radius
diagnostic is only moderately predictive (0.737 and 0.675), and the large AUC reported in version 1 came
from a diagnostic costing 46 ms per event. The stored-state advantage claimed in version 1 does not
exist.
