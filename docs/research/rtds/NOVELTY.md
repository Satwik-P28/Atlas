# Novelty assessment: decision impact of authentic data revisions

Scope of the check: a targeted review of (i) the real-time data revision literature, (ii) sensitivity
and post-optimality analysis in mathematical programming, and (iii) value-of-information work. It is
not an exhaustive systematic review, and it was done by searching for the standard reference points in
each area rather than by reading the whole literature.

## What is already established

**Revisions are large and not well behaved.** Croushore and Stark (2001) built the real-time dataset
this study's source family descends from; Aruoba (2008) shows revisions violate the properties
forecasters would like (mean-zero, uncorrelated with preliminary values, shrinking); Jacobs and van
Norden (2011) model the measurement-error dynamics; Croushore (2011) surveys the forecasting
consequences. It is therefore *not* novel to observe that revisions are economically substantial, and
this study does not claim that.

**Revisions change forecasts and estimates.** Giannone, Reichlin and Small (2008) quantify the effect of
each release on a GDP nowcast; Ghysels, Horan and Moench (2018) show revisions can account for a sizeable
share of measured return predictability. The idea "revisions change what an econometric user computes"
is well covered — for prediction, estimation and inference.

**Sensitivity and post-optimality are classical.** Fiacco (1983) and Gal and Greenberg (1997) cover
parametric programming, including the range of cost perturbations over which a basis or active set stays
optimal; Best and Chakravarti (1990) is one of many sources for active-set methods. The question "does
the optimum change when the objective changes" is not new, and neither is the answer that it changes
exactly when the active set fails to remain optimal.

**Value of information** (Howard 1966) frames "what is a revision worth" as a decision-theoretic
quantity. Nothing in this study improves on it.

## What appears to be unoccupied

The intersection: **revision metadata from official statistics used as the evidence base for a
decision-level, post-optimisation audit**, with the revision's publication instant as the temporal
boundary. Concretely, three things do not appear together in the literature this search found:

1. **A decision-level materiality statistic for authentic revisions.** The revision literature measures
   revisions in the units of the data (percentage points of GDP, thousands of jobs) or in forecast-error
   units. It does not typically ask "did this revision change the argmin of a program, and by how much
   in objective units". That is the statistic this study reports — and it is not a restatement of
   revision size, which is the point of §4.4.
2. **The two-clock audit framing for revisions.** Real-time datasets are built to prevent look-ahead in
   *estimation*; the same discipline applied to *decision* audit (public availability and economic
   effective time as separate gates, resolved against an audit clock) is a reuse of an established idea
   in a place it is not usually applied.
3. **A negative result about certification redundancy.** The finding that a duality-based certificate's
   certified set coincides exactly with the classical active-set stability set — on real revisions, in
   two independent revision processes — is a statement about what such certificates buy. It is a
   caution for the "certified decision audit" idea rather than a promotion of it, and it is the kind of
   result that is only visible when a certificate is run on data whose revisions were not designed to
   make it look good.

## Positioning

The correction pass narrowed this further, and the narrowing is part of the assessment. Version 1's
most quotable claim (geometry predicts materiality with AUC 0.88/0.94) depended on a directional
stability radius that re-runs the same optimality tests the outcome is defined by; without it the AUC is
0.68/0.74. Version 1's storage claim was an artefact of comparing an insufficient record with a complete
model. What remains novel is therefore the benchmark, the measurement discipline, and three negative
results — not a predictive score.

The contribution is **an empirical benchmark and a measurement method**, not an algorithm:

* a reusable, provenance-documented dataset of decision/audit pairs built from 1,009 real-time vintages;
* a protocol that separates materiality from revision size and reports both;
* an evaluation harness that scores certificates, active-set tests, first-order and strong-convexity
  bounds, worst-case certificates and no-recomputation against re-solving;
* two negative results (magnitude is uninformative; the certificate is redundant with the active-set
  test here) and one positive one (geometry predicts materiality with AUC 0.88/0.94 out of sample).

No claim of a new theorem, a new solver, or a decision-quality improvement is made. The mathematical
content is classical duality and standard post-optimality analysis; the novelty, to the extent there is
any, is in what is measured and in the honesty of the measurement — including that the measurement
required a correction which removed two of the three headline claims.
