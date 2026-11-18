# Generated tables

Produced by `scripts/research/rtds_tables.py` from `results.json` and `dataset.json`. Do not hand-edit.

Convention: c_D + delta == -z_A for every event; asserted, not assumed.

## Data

| cohort | frequency | series | vintage responses | train | pilot | test | holdout |
|---|---|---|---|---|---|---|---|
| A | quarterly | GDPC1, GPDIC1, GCEC1, EXPGSC1 | 1338 | 52 | 8 | 38 | 4 |
| B | monthly | PAYEMS, MANEMP, USCONS | 1009 | 156 | 24 | 114 | 12 |

Horizon rule: audit vintage = first vintage on or after add_months(decision, 12). A vintage date is a release date and is treated as available at 23:59:59 UTC; no intraday claim is made.

**Audit-vintage change from the superseded 400/366-day horizons.**

| cohort | paired events | audit vintage unchanged | audit vintage changed | median horizon (days) |
|---|---|---|---|---|
| A | 98 | 0 | 98 | 392 |
| B | 294 | 292 | 2 | 392 |

## Materiality and certification (confirmatory test split)

| cohort | events | material (95% cluster CI) | certified immaterial | certified material | unknown | false immaterial | false material |
|---|---|---|---|---|---|---|---|
| A | 38 | 73.7% [41.7%, 91.7%] | 8 (21.1%) | 28 (73.7%) | 2 (5.3%) | 0 | 0 |
| B | 114 | 50.0% [30.6%, 63.9%] | 51 (44.7%) | 57 (50.0%) | 6 (5.3%) | 0 | 0 |

`certified material` is established by a feasible descent (a lower bound on regret), never by an upper bound above the threshold. `unknown` is the honest third category: neither claim is justified.

**Untouched later period (2024-07-01 .. 2025-06-30), first computed here.**

| cohort | events | material | certified immaterial | certified material | unknown |
|---|---|---|---|---|---|
| A | 4 | 25.0% | 75.0% | 25.0% | 0.0% |
| B | 12 | 58.3% | 33.3% | 58.3% | 8.3% |

**Superseded versus corrected (test split).**

| cohort | materiality (v1) | materiality (v2) | certified immaterial (v1) | certified immaterial (v2) | CRI-vs-KKT agreement (v1) | CRI-vs-KKT agreement (v2) |
|---|---|---|---|---|---|---|
| A | 63.2% | 73.7% | 28.9% | 21.1% | 11/0/0 | 8/0/0 |
| B | 47.4% | 50.0% | 42.1% | 44.7% | 48/0/0 | 51/0/0 |

The v1 columns are not comparable on the merits: they describe the program `z_A - 2 z_D`, which is not the model the protocol defines. Agreement cells are `certified and KKT-stable / certified but not stable / stable but not certified`.

## Attribution: what the correction changed, and why

| cohort | paired test events | audit vintage changed | audit growth changed | material: v1 | material: mapping fixed, old horizon | material: v2 | certified: v1 | certified: mapping fixed | certified: v2 |
|---|---|---|---|---|---|---|---|---|---|
| A | 38 | 38 | 3 | 24/38 | 27/38 | 28/38 | 11/38 | 9/38 | 8/38 |
| B | 114 | 1 | 0 | 54/114 | 57/114 | 57/114 | 48/114 | 51/114 | 51/114 |

The middle arm isolates the sign error: same audit vintages as the superseded study, documented cost convention. The difference between the middle and last columns is the calendar-horizon repair.

## Certificate coverage, abstention and soundness

| cohort | method | immaterial certificates | material certificates | abstentions | decisions certified | false immaterial | immaterial events covered |
|---|---|---|---|---|---|---|---|
| A | CRI regret bound <= tau (validated upper bound) | 8 | 0 | 30 | 21.1% | 0 | 8/10 |
| A | CRI certificate + feasible-repair materiality witness | 8 | 28 | 2 | 94.7% | 0 | 8/10 |
| A | active-set / KKT stability (implies regret 0) | 8 | 0 | 30 | 21.1% | 0 | 8/10 |
| A | strong-convexity upper bound <= tau | 0 | 0 | 38 | 0.0% | 0 | 0/10 |
| A | CRI-U: further correction beyond the audit vintage | 0 | 0 | 38 | 0.0% | 0 | 0/10 |
| A | CRI-U: correction relative to the decision vintage | 0 | 0 | 38 | 0.0% | 0 | 0/10 |
| A | no recomputation (asserts regret 0 for every event) | 38 | 0 | 0 | 100.0% | 28 | 38/10 |
| B | CRI regret bound <= tau (validated upper bound) | 51 | 0 | 63 | 44.7% | 0 | 51/57 |
| B | CRI certificate + feasible-repair materiality witness | 51 | 57 | 6 | 94.7% | 0 | 51/57 |
| B | active-set / KKT stability (implies regret 0) | 51 | 0 | 63 | 44.7% | 0 | 51/57 |
| B | strong-convexity upper bound <= tau | 0 | 0 | 114 | 0.0% | 0 | 0/57 |
| B | CRI-U: further correction beyond the audit vintage | 0 | 0 | 114 | 0.0% | 0 | 0/57 |
| B | CRI-U: correction relative to the decision vintage | 0 | 0 | 114 | 0.0% | 0 | 0/57 |
| B | no recomputation (asserts regret 0 for every event) | 114 | 0 | 0 | 100.0% | 57 | 114/57 |

A method that only produces an upper bound can certify immateriality and nothing else; its `material certificates` column is zero by construction, so its old `accuracy` figure (which counted `bound > tau` as a materiality claim) has been withdrawn.

**Ranking heuristics (predictions, not certificates).**

| cohort | heuristic | AUC |
|---|---|---|
| A | revision magnitude (log l2 delta cost) | 0.425 |
| A | first-order estimate (absolute) | 0.379 |
| A | CRI regret upper bound (absolute) | 0.900 |
| B | revision magnitude (log l2 delta cost) | 0.540 |
| B | first-order estimate (absolute) | 0.517 |
| B | CRI regret upper bound (absolute) | 0.974 |

## CRI certificates versus the classical active-set test

| cohort | certified and KKT-stable | certified but not stable | stable but not certified | test events |
|---|---|---|---|---|
| A | 8 | 0 | 0 | 38 |
| B | 51 | 0 | 0 | 114 |

**Bound tightness.**

| cohort | median bound, material | median bound, immaterial | median bound / regret (material) | median lower bound, material | median lower / regret (material) |
|---|---|---|---|---|---|
| A | 0.135 | 1.21e-14 | 4.258 | 0.016 | 1.000 |
| B | 0.108 | 7.67e-15 | 5.256 | 0.019 | 1.000 |

## What predicts materiality

| cohort | feature group | features | AUC | 95% cluster CI | radius used | median feature cost (ms) | KKT checks per event |
|---|---|---|---|---|---|---|---|
| A | magnitude | delta_cost_l2 | 0.425 | [13.8%, 70.1%] | no | 0.00 | 0.0 |
| A | metadata | changed_inputs, revision_index, benchmark | 0.537 | [41.4%, 64.4%] | no | 0.00 | 0.0 |
| A | geometry_no_radius | delta_cost_l2, binding, condition | 0.675 | [48.9%, 84.8%] | no | 0.00 | 0.0 |
| A | geometry_projection | delta_cost_l2, binding, condition, delta_cost_on_decision | 0.686 | [54.0%, 82.1%] | no | 0.00 | 0.0 |
| A | geometry_full | delta_cost_l2, binding, condition, delta_cost_on_decision, log_radius | 0.911 | [77.9%, 100.0%] | yes | 46.40 | 28.0 |
| B | magnitude | delta_cost_l2 | 0.540 | [41.4%, 69.7%] | no | 0.00 | 0.0 |
| B | metadata | changed_inputs, revision_index, benchmark | 0.462 | [38.9%, 53.4%] | no | 0.00 | 0.0 |
| B | geometry_no_radius | delta_cost_l2, binding, condition | 0.737 | [66.2%, 82.3%] | no | 0.01 | 0.0 |
| B | geometry_projection | delta_cost_l2, binding, condition, delta_cost_on_decision | 0.750 | [67.1%, 83.4%] | no | 0.00 | 0.0 |
| B | geometry_full | delta_cost_l2, binding, condition, delta_cost_on_decision, log_radius | 0.962 | [94.8%, 98.3%] | yes | 46.27 | 37.0 |

The directional stability radius is a diagnostic, not free metadata: it runs a bracketing search of multiplier recoveries and KKT checks along the observed revision, and its cost is charged to the group that uses it.

## Computational cost and stored state

| cohort | decision | certificate | compile | repair | active-set | warm re-solve | internal re-solve | OSQP re-solve | radius search |
|---|---|---|---|---|---|---|---|---|---|
| A | 4.63 | 2.06 | 0.26 | 0.21 | 1.30 | 4.25 | 4.20 | 1.14 | 43.21 |
| B | 4.26 | 2.00 | 0.25 | 0.13 | 1.30 | 4.54 | 4.55 | 1.08 | 40.84 |

**Stored state per decision (bytes).**

| cohort | sufficient audit record | shared structure (once) | amortized shared | record + amortized | audit-vintage cost vector only | cost vector + amortized | full serialised problem |
|---|---|---|---|---|---|---|---|
| A | 736 | 634 | 6.2 | 742.2 | 83 | 89.2 | 1080 |
| B | 673 | 390 | 1.3 | 674.3 | 63 | 64.3 | 807 |

The record carries the recorded weights, the recorded multipliers and the decision-time linear costs; the quadratic matrix, bounds and constraint rows are shared and stored once. `cost vector only` is what a re-solve needs per decision once the same structure is shared.

## Sensitivity to the risk weight and the materiality threshold

| cohort | risk weight rho | events | material tau=1e-2 | tau=1e-3 | tau=1e-4 | certified immaterial tau=1e-3 |
|---|---|---|---|---|---|---|
| A | 0.02 | 38 | 26.3% | 34.2% | 34.2% | 65.8% |
| A | 0.05 | 38 | 28.9% | 34.2% | 36.8% | 60.5% |
| A | 0.2 | 38 | 31.6% | 44.7% | 50.0% | 50.0% |
| A | 1 | 38 | 47.4% | 73.7% | 73.7% | 21.1% |
| B | 0.02 | 114 | 25.4% | 28.1% | 31.6% | 68.4% |
| B | 0.05 | 114 | 25.4% | 28.1% | 29.8% | 68.4% |
| B | 0.2 | 114 | 25.4% | 31.6% | 35.1% | 64.9% |
| B | 1 | 114 | 34.2% | 50.0% | 54.4% | 44.7% |

