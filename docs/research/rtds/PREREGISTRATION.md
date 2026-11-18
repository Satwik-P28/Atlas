# Preregistration: decision materiality of authentic macroeconomic data revisions

**Status:** written before any confirmatory experiment was run. The commit that contains this file
precedes the commit that contains `artifacts/research/rtds/results.json`. If any endpoint below is
changed after seeing test results, the change is recorded in §9 of this file and in the research
report as *exploratory*, with the original wording preserved.

**Branch:** `research/real-world-revision-study`, from CRI commit `8e666a0`.

## 1. Question

When a published macroeconomic observation is revised, how often does the revision change the optimal
decision of a fixed convex resource-allocation program, and how accurately can that fact be
established from the original decision and audit-time evidence without re-solving?

## 2. Data

Primary source: **ALFRED** (the archival companion of FRED, Federal Reserve Bank of St. Louis), read
through its public real-time endpoints:

* vintage dates per series: `https://alfred.stlouisfed.org/series/downloaddata?seid=<ID>`
* one vintage of one series: `https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=<ID>&vintage_date=<DATE>`

The second endpoint was verified to return the *vintage* series (not the current one) before this
protocol was written: GDPC1 for 2014-10-01 reads 16,311.6 at vintage 2015-01-30, 16,294.7 at
2015-03-27, and 16,186.7 at 2016-07-29; PAYEMS for 2014-12-01 reads 140,347, then 140,592, then
140,402 across the same span. Raw responses are cached locally and hashed; the archive stores derived
event records and digests, not the vendor's raw files.

Two cohorts, analysed **separately and never pooled**, because they are different revision processes:

* **Cohort A — BEA quarterly expenditure components.** `GDPC1`, `PCEC1`, `GPDIC1`, `GCEC1`
  (real GDP, personal consumption, gross private domestic investment, government consumption).
  Vintage structure: advance / second / third estimate, then annual benchmark revisions.
  *Erratum, recorded rather than rewritten:* `PCEC1` turned out to have no ALFRED vintage archive, so
  the implemented cohort uses `EXPGSC1` (real exports of goods and services) in its place; see
  amendment **A0** in §9. The list above is left as it was written.
* **Cohort B — BLS monthly payroll employment.** `PAYEMS`, `MANEMP`, `USCONS` (total nonfarm,
  manufacturing, construction). Vintage structure: monthly first print, two monthly revisions, then
  the annual benchmark.

The Philadelphia Fed RTDSM was assessed and *not* used: its data files are no longer published at a
stable public URL (the documented `/-/media/.../real-time-data/` paths return the site's 404 page),
so reproducing a study from it would depend on an undocumented path. This is recorded as an
accessibility finding, not a criticism of the dataset. BLS archived release tables were assessed as a
secondary possibility and not used: they publish revision tables per release, but joining them to
vintages requires the same release calendar ALFRED already encodes, with more parsing risk.

**Time policy.** A vintage date is a *release date*, not an intraday timestamp. Every vintage is
therefore treated as available only at the **end** of its release date, 23:59:59 UTC, and a decision
clock is the first vintage date whose release is complete at that instant. No intraday availability
is claimed anywhere. This is conservative in the only direction that matters for a look-ahead claim:
it can delay a revision's eligibility, never advance it. The limitation is stated in the report.

**Rights.** ALFRED/FRED data are redistributed by the Federal Reserve Bank of St. Louis subject to its
terms of use (attribution, no implied endorsement); the underlying series are US government
statistics in the public domain. This repository stores only derived event records, URLs and SHA-256
digests of the fetched responses; raw files stay in a git-ignored cache.

## 3. Splits (frozen before the study is run)

| Split | Decision clocks | Use |
|---|---|---|
| `train` | 2000-01-01 – 2012-12-31 | estimate the covariance `Q`, the standardisation of the mapping, and the classifier |
| `pilot` | 2013-01-01 – 2014-12-31 | pipeline validation only; reported but **excluded** from confirmatory estimates |
| `test` | 2015-01-01 – 2024-06-30 | confirmatory cohort |

Test events need an audit vintage at the horizon, so the last usable decision clock is bounded by data
availability, not by preference.

## 4. Decision model (fixed before estimation)

A capacity-allocation program in `n` lines (n = 4 for cohort A, 3 for cohort B):

```
minimise    0.5 · x' Q x  −  c' x
subject to  sum(x) = 1,  0 ≤ x ≤ 0.6,
            x[government] ≥ 0.15,  x[investment] ≤ 0.45      (cohort A)
            x[manufacturing] ≥ 0.20                            (cohort B)
```

* `Q = ρ · corr(G)` where `G` is the matrix of **first-release** growth vectors in the `train` split
  and `ρ = 0.05`. `ρ` is a modelling parameter, not an estimate; sensitivity at `ρ ∈ {0.01, 0.2}` is
  prespecified as secondary.
* `c = −z`, where `z` is the growth vector standardised with the `train` split's mean and standard
  deviation. Growth at a clock is `v(q)/v(q−1) − 1` computed **within one vintage**, which is what an
  analyst could compute at that instant. The map from growth to cost is a prespecified linear
  transformation; it is **not** claimed to be empirically identified, and the report says so.
* The model is a *counterfactual decision model*: the economic observations are real, the decisions
  are generated by this program, and no historical operational decision is being audited.

## 5. Events

For each observation period `q` in the split:

* `D(q)` = earliest vintage date at which any cohort series reports a value for `q` (the first print).
* `A(q)` = earliest vintage date at least 4 quarters (cohort A) / 12 months (cohort B) after `D(q)`.
* Event = `(q, D(q), A(q))`, one per observation period. A revision of one observation in one release
  is never counted as several events, and two observations revised on one release are **one** decision
  event, not two.

Excluded and counted, with reasons: any series missing at either clock; `A(q) = D(q)`; the event's
decision clock outside the split; a vintage whose fetch failed or whose digest changed on re-fetch.

## 6. Hypotheses and primary endpoints

**H1 (materiality).** A nontrivial fraction of authentic revisions changes the optimal decision.
*Primary endpoint:* share of test events with `regret > τ`, `τ = 1e-3` objective units, where
`regret = f_A(x_D) − f_A*` computed with two independent solvers. "Nontrivial" is operationalised as
the lower bound of the 95% clustered interval exceeding 10%.

**H2 (immaterial revisions are certifiable).** Some revisions with nonzero numerical magnitude leave
the decision certifiably immaterial. *Secondary endpoint:* among events with `‖Δc‖₂ > 0` and
`regret ≤ τ`, the share whose CRI bound is `≤ τ`.

**H3 (magnitude is insufficient).** Revision size alone poorly predicts materiality.
*Primary endpoint:* out-of-sample AUC of a magnitude-only logistic model, compared with a
geometry-aware model that adds the projected revision on the active/directions, the distance to an
active-set transition, and problem conditioning. "Insufficient" is operationalised as magnitude-only
AUC ≤ 0.80, or the geometry-aware model's AUC exceeding it by ≥ 0.05 with non-overlapping clustered
intervals.

**H4 (certification usefulness varies with geometry).** *Secondary endpoint:* certified-in-time share
by active-set configuration (constraint pattern at the decision) and by `ρ`, reported as a table.

**H5 (certification vs reoptimisation).** *Secondary endpoint:* for each method, the trade-off between
audit-time cost and information retained, with the regime in which each is preferable stated
explicitly. No single "winner" claim: the comparison is by workflow requirement.

## 7. Competing methods

1. Full reoptimisation with OSQP (ground truth for timing and, with the internal solver, for regret).
2. Warm-start reoptimisation from the recorded weights.
3. Active-set stability test: are the recorded weights still KKT-optimal under the revised costs?
4. Conventional sensitivity bound: first-order/Taylor estimate (`first_order_estimate`) and the
   strong-convexity bound (`strong_convexity_bound`).
5. No-recomputation baseline: assert zero regret.
6. CRI (residual certificate / duality gap from the recorded multipliers).
7. CRI-U: worst-case certificate over a declared interval set around the revised costs, sized by the
   training-split revision dispersion (`interval_set` + `certify_worst_case`), for the events where a
   single audit-time point estimate is not the right object.

## 8. Statistics

* Clustering: by **decision year** (cohort A) / decision year (cohort B, 12 monthly events per year).
  Intervals by moving-block bootstrap over years (block 2 chapters), 2000 resamples.
* Multiplicity: one primary test per cohort (H1, H3). Everything else is secondary and labelled.
* Sensitivity: `τ ∈ {1e-2, 1e-3, 1e-4}`, `ρ ∈ {0.01, 0.05, 0.2}`, mapping variants (raw growth,
  log growth, sign only), and horizon (1, 2, 4 quarters for A; 3, 6, 12 months for B) — all declared
  secondary, reported as a grid rather than as a single number.
* A result that contradicts the hypothesis is reported as such.

## 9. Amendments

Amendments are recorded in the order they were made, and each is labelled with what was known at the
time. The distinction matters: this study's 2015–2024H1 results were inspected before amendments A4–A9
existed, so corrected results from that sample are a **reanalysis**, not a pristine confirmation. See
[CORRECTIONS.md](CORRECTIONS.md) for the defects behind A4–A8.

### Pre-confirmatory (written before any test-split regret was computed)

**A0. Series substitution in cohort A.** `PCEC1` (real personal consumption expenditures) has no
ALFRED vintage archive — its download page returns 404 — so no real-time vintage series exists to
build decision events from. The cohort was built from `EXPGSC1` (real exports) instead, keeping the
cohort at four series and keeping the substitution visible: it was made while building the dataset,
before any test-split regret was computed, and it is not a modelling choice about revisions. A
reader who wants personal consumption in the cohort would have to source its vintages elsewhere. The
only other real expenditure aggregate with a complete ALFRED archive at the time of building was
exports; the report records that this is a convenience substitution, not an economic argument.

**A1. Risk weight.** §4 fixed `ρ = 0.05` without knowing its
scale against standardised growth. The value was not simply changed: a rule was prespecified — choose
ρ from {0.25, 0.5, 1, 2} to maximise the share of **train-split** events with an interior optimum, ties
broken towards 1 — and it selected `ρ = 1.0` (all four values tied at 1.0, so the tie-break decided).
The rule was written after this protocol but before any confirmatory computation: no test-split regret
had been computed when it was applied. It proved non-discriminating, because with `Σx = 1` a solution
is almost never entirely on box bounds; the choice is therefore defended by the sensitivity grid of
§4.6, which retains the protocol's original values (0.02, 0.05, 0.2).

**A2. Added predictor set (secondary, labelled exploratory).** The primary H3 comparison is
magnitude versus geometry. A third set — magnitude plus revision metadata (number of changed inputs,
release index, benchmark-window flag) — was added to test the specific question in Phase 6 of the
mission: whether metadata carries information beyond the size of the correction. It is reported in
§4.4 beside the prespecified models and is not used for any primary decision.

**A3. Interval method for AUC (secondary).** A cluster bootstrap over decision years was added to put
an interval on the out-of-sample AUC. This is a presentation choice, not a change of endpoint.

### Post-hoc (made after version 1's results had been observed, in response to review)

**A4. Objective coefficient convention (substantive; supersedes the protocol's arithmetic).** §4 did not
state a sign convention for the mapping from standardised growth to the objective's linear cost. One is
now fixed: `c = -z`, and a revision is a change in `c` applied with a positive identity sensitivity, so
`delta = c_A - c_D = z_D - z_A`. The previous implementation produced `z_A - 2 z_D`. The convention is
asserted against an independently constructed audit program for every event. Endpoints are unchanged;
the model they were computed on is corrected.

**A5. CRI-U base and set (substantive).** §7's worst-case arm previously passed an absolute cost level
as the centre of a perturbation set. It is now two declared arms — further corrections relative to the
audit-time program, and the total correction relative to the decision-time program — each centred at
zero, with widths estimated on the train split only. Results for both are reported.

**A6. Three-way outcome classification (substantive).** §6 scored methods by accuracy, counting
`upper bound > τ` as a materiality claim. Outcomes are now `certified immaterial` (upper bound ≤ τ),
`certified material` (independently established lower bound > τ) and `unknown`. Accuracy is no longer
reported for methods that only produce upper bounds; coverage, abstention and false-certificate counts
replace it. This is a stricter reading of the existing H2 and H4 endpoints, not a new endpoint.

**A7. Calendar horizon (substantive).** §3 said four calendar quarters (A) and twelve calendar months
(B); the code used 400 and 366 days. The horizon is now `add_months(decision, 12)` for both. The audit
vintage changes for every quarterly event, so this is a data change, not a reporting change.

**A8. Feature groups and the stability radius (substantive, exploratory).** The geometry predictor is now
reported as five prespecified groups, separating the directional stability radius from features that are
free given the recorded decision and the revision, and charging the radius's KKT evaluations to the group
that uses it. The v1 headline AUC depended on that radius; §4.4 of the report reports both.

**A9. Stored-state accounting (corrects a claim, adds no endpoint).** The audit record is now the
smallest representation that a fresh process can certify from (weights, multipliers, decision-time
costs, clocks, digests) plus a per-cohort shared block, and its size is compared with the marginal
representation a re-solve needs rather than with a full serialised problem.

### Samples

**A10. Prespecified sensitivity experiments: what was run, and what was not.** §7 prespecified four
secondary sensitivity families. Reported here so the record is complete rather than selective:

* **Threshold** `τ ∈ {1e-2, 1e-3, 1e-4}`: **run**, both cohorts (§4.8 of the report).
* **Risk weight**: **run**, but not exactly as written. §7 listed `ρ ∈ {0.01, 0.05, 0.2}`; the grid used
  `{0.02, 0.05, 0.2, 1.0}`. `0.01` was replaced by `0.02` (the smaller value left almost every solution
  on a corner, so the two are indistinguishable in the grid), and `1.0` was added because it is the
  calibrated value actually used.
* **Mapping variants** (raw growth, log growth, sign only): **not run.** Each variant changes `c` and
  therefore the whole pipeline; running three more full passes was not done, so the report's claims are
  conditional on the declared mapping and are not evidence about its functional form. This is a gap, not
  a null result.
* **Horizon grid** (1, 2, 4 quarters for A; 3, 6, 12 months for B): **not run.** It now requires
  rebuilding the event archive at each horizon (the builder is calendar-aware, so this is feasible) and
  was out of scope for the correction pass. The report's horizon statements are therefore about twelve
  calendar months only.

**S1. Untouched later period (exploratory, added post hoc).** 2024-07-01 .. 2025-06-30 was never
computed before this correction pass. It is reported separately, with all parameters fixed on the train
split. Cohort A yields 4 events, which cannot settle anything; it is reported as a description and is not
used for any confirmatory claim.

**S2. Reanalysis label.** The preregistered test split (2015-01-01 .. 2024-06-30) has been inspected. Its
corrected results are reported as a reanalysis of the same period, not as a new confirmation.
