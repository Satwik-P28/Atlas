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
3. **A negative result about certification redundancy, and about its incremental value.** The finding
   that a duality-based certificate's certified set coincides exactly with the classical active-set
   stability set — on real revisions, in two independent revision processes — is a statement about what
   such certificates buy. The version-3 comparison makes it sharper: a combined KKT-stability +
   feasible-descent workflow reproduces every verdict, and an OSQP re-solve is faster than both while
   settling every event. It is a caution for the "certified decision audit" idea rather than a promotion
   of it, and it is the kind of result that is only visible when a certificate is benchmarked against the
   obvious simpler workflow on data whose revisions were not designed to make it look good.

## Positioning

The correction passes narrowed this further, and the narrowing is part of the assessment. Version 1's
most quotable claim (geometry predicts materiality with AUC 0.88/0.94) depended on a directional
stability radius that re-runs the same optimality tests the outcome is defined by; without it the AUC is
0.68/0.74. Version 1's storage claim was an artefact of comparing an insufficient record with a complete
model, and disappears entirely (1.2× larger, not smaller) once both workflows are charged the same
decision state. And the headline coverage of version 2 turned out to be a property of the two-sided
workflow: the certificate adds nothing over KKT stability + descent, while a re-solve is faster than
either. What remains novel is therefore the benchmark, the measurement discipline, and four negative
results — not a predictive score and not an algorithm.

The contribution is **an empirical benchmark and a measurement method**, not an algorithm:

* a reusable, provenance-documented dataset of decision/audit pairs built from 1,009 real-time vintages;
* a protocol that separates materiality from revision size and reports both;
* an evaluation harness that scores certificates, active-set tests, first-order and strong-convexity
  bounds, worst-case certificates and no-recomputation against re-solving;
* four negative results: revision magnitude is uninformative about materiality; the certificate is
  redundant with the active-set test; the certificate adds no classification utility over KKT +
  feasible descent and is slower than an OSQP re-solve; and it has no storage advantage; plus the
  conditional description of when worst-case (CRI-U) certification fails at this tolerance.

No claim of a new theorem, a new solver, or a decision-quality improvement is made. The mathematical
content is classical duality and standard post-optimality analysis; the novelty, to the extent there is
any, is in what is measured and in the honesty of the measurement — including that the measurement
required two correction passes which removed the headline claims, and a baseline comparison which
removed the last one.

## What this study does *not* license

Because the mapping `c = -z` is declared rather than estimated, and because the prespecified mapping and
horizon sensitivity families were never executed, nothing here supports statements about revision
materiality under another cost function or another audit horizon. The redundancy and dominance results
are measured at four and three assets, where a re-solve costs under a millisecond; they say nothing about
regimes where re-solving is expensive or unavailable, which is the only place a certificate could still
earn its keep.
