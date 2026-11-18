# Prior art and novelty audit

**Scope.** This audit covers work relevant to decision-making under *revised and delayed
evidence*, with emphasis on (i) sensitivity and stability analysis of convex programs, (ii)
decision-focused learning and conformal/robust decision pipelines, (iii) distributionally
robust and data-quality-aware optimisation, and (iv) portfolio decision problems with costs.
Coverage is through November 2026.

**Verification status of citations.** Entries marked **[fetched]** were retrieved and read
from the publisher or proceedings page during this pass, and the stated formulation
corresponds to the abstract/introduction of the source. Entries marked **[standard]** are
long-established references cited from the literature; their bibliographic details should be
re-checked before any external submission. No citation here should be read as an endorsement
that a paper's results were reproduced in this repository.

---

## 1. The specific question this branch asks

> A decision was computed at time `t` from evidence available at `t`. Evidence has since been
> revised or corrected. Can we determine, **without re-solving**, whether the recorded
> decision is still optimal for the corrected decision problem, and if not, can we bound its
> regret?

This is narrower than "how does the optimum move when parameters change" and narrower than
"how should a model be trained so its decisions are robust". It is an *audit* question about
a decision that already exists.

---

## 2. Sensitivity and stability of convex programs

| Work | Problem | Contribution | Relationship to this branch |
|---|---|---|---|
| Ghaffari Hadigheh & Terlaky, *Sensitivity analysis in convex quadratic optimization: invariant support set interval* (2004, revised; published in *Algorithmic Operations Research*, 2007) **[fetched]** | Convex QP with perturbations in the right-hand side and in the linear objective term | Computable auxiliary problems giving the interval of parameter variation over which the **support set** of a given primal optimum stays invariant (Type II / support-set invariancy) | The closest classical ancestor of the *exact* certificate. Our exact test is the same invariancy question asked in KKT form, with the multiplier vector recovered by a non-negative feasibility problem rather than by a parametric auxiliary LP. **Not new as mathematics.** |
| Kheirfam, *Sensitivity analysis in multi-parametric strictly convex quadratic optimization*, Matematički Vesnik 62 (2010) **[fetched]** | Simultaneous multi-parametric perturbations of RHS and linear objective term | Shows invariancy regions are convex polyhedral sets; describes them by basis vectors and extreme directions | Explains *why* the invariance radius along a ray is an interval (our Proposition 4). We rely on the polyhedrality rather than re-deriving it. |
| Kheirfam, *Sensitivity analysis in convex quadratic optimization: simultaneous perturbation of the objective and right-hand-side vectors*, Algorithmic Operations Research (2007) **[fetched]** | Parametric convex QP | Optimal value function is piecewise quadratic; transition points and invariancy intervals; left/right derivatives via LPs | Directly relevant to our Proposition 5 (convexity of regret along a ray). The piecewise-quadratic structure is stronger than what we use; we only need convexity. |
| Pacaud, *Sensitivity analysis for parametric nonlinear programming: a tutorial* (2025 preprint) **[fetched]** | Survey of Fiacco-style sensitivity, degenerate NLPs, conic programs, approximate interior-point solutions | Extends sensitivity to degenerate problems with non-unique duals and to approximate solutions | Motivates our treatment of degeneracy as a first-class case: with a singular risk matrix the dual bound does not exist and only the exact test remains. |
| Fiacco, *Introduction to Sensitivity and Stability Analysis in Nonlinear Programming* (1983) **[standard]** | Classical sensitivity theory | Implicit-function and KKT-based derivatives of primal-dual solutions under strict complementarity and regularity | The assumption set we explicitly check numerically (strict complementarity is exactly what fails in our corner cases). |
| Boyd & Vandenberghe, *Convex Optimization* (2004) **[standard]** | Duality, KKT sufficiency, perturbation and sensitivity | Weak duality, KKT sufficiency for convex problems, dual function interpretation | Supplies Propositions 1–3. Nothing in our certificate machinery is beyond this textbook; that is a feature, not a claim of novelty. |

**Assessment.** The *mathematical content* of the certificate is classical post-optimality
analysis. A reviewer would be right to say so. What this branch contributes is not a new
sensitivity theorem.

---

## 3. Decision-focused learning and robust decision pipelines

| Work | Problem | Contribution | Relationship |
|---|---|---|---|
| Yamao, Kobayashi, Matsui, Nagai, Nishimura, Nakata, *Robust Decision-Focused Learning via Worst-Case Regret Minimization*, UAI 2026 (PMLR 337) **[fetched]** | Predict-then-optimise with unknown objective coefficients | Two robust regret losses: worst-case regret over an uncertainty set around the observed coefficients (measurement error), and worst-case regret over a Wasserstein ambiguity set (distribution shift); Danskin-based subgradients | Addresses *training* under coefficient uncertainty. We do not train; we audit a fixed decision. Their uncertainty-set construction is the nearest methodological neighbour to "perturbation derived from evidence properties". |
| Schutte, Postek, Yorke-Smith, *Robust Losses for Decision-Focused Learning*, IJCAI 2024 **[fetched]** | Empirical regret as a surrogate for expected regret | Three loss functions approximating expected regret more robustly under aleatoric and epistemic uncertainty; no extra cost per epoch | Confirms that *regret*, not prediction error, is the right target. We measure realized regret directly and certify bounds on it. |
| Patel, Rayan, Tewari, *Conformal Contextual Robust Optimization*, AISTATS 2024 (PMLR 238) **[fetched]** | Predict-then-optimise with conformal uncertainty regions | Conformal-Predict-Then-Optimize: nonconvex conformal regions from conditional generative models with distribution-free coverage; visual summaries of the region | The strongest existing answer to "calibrate the uncertainty set from data". Our branch deliberately does **not** claim a calibrated radius; the perturbation is *declared* by an explicit sensitivity and the guarantee is conditional. This is a materially weaker and more honest claim, and it is the main reason Candidate A was not selected. |
| Farhat et al., *On the Robustness of Decision-Focused Learning* (arXiv 2311.16487, 2025 revision) **[fetched]** | Adversarial robustness of eleven DFL methods | Worst-case input perturbations degrade downstream decisions; robustness correlates with predicting near-optimal decisions | Independent evidence that small input perturbations can move decisions. Supports the premise; does not address auditing a past decision. |
| Kiyani et al., *Decision Theoretic Foundations for Conformal Prediction*, ICML 2025 (PMLR 267); *Utility-Directed Conformal Prediction*, ICLR 2025 **[listed, not fetched]** | Conformal prediction with decision-theoretic utility | Coverage that is aligned with downstream utility rather than marginal coverage | Would be the correct comparison if we had claimed calibrated coverage. We do not. |
| Elmachtoub & Grigas, *Smart "Predict, then Optimize"*, Management Science (2022) **[standard]** | SPO losses for predict-then-optimise | Decision-aware training | Establishes the regret-versus-error distinction used throughout. |

**Assessment.** This literature is about **choosing/training** a decision under uncertainty.
It is not about **auditing a recorded decision against corrected evidence**, and it does not
supply a cheap certified regret bound for an already-made decision. That gap is real, but it
is a gap in *problem framing*, not a gap in optimisation theory.

---

## 4. Robust and distributionally robust optimisation

| Work | Contribution | Relationship |
|---|---|---|
| Ben-Tal & Nemirovski, *Robust solutions of uncertain linear programs* (1998/1999) **[standard]** | Robust counterpart of LP under ellipsoidal/box uncertainty | Supplies the fixed-radius baselines. Our experiment reports a **negative structural finding**: a box ambiguity set on the linear costs is *vacuous* for a long-only fully-invested book, because `‖w‖₁` is constant on the budget simplex. The ellipsoidal counterpart is not vacuous because `‖w‖₂` is not constant. |
| Bertsimas, Brown, Caramanis, *Theory and applications of robust optimization*, SIAM Review (2011) **[standard]** | Survey; price of robustness | Framing for fixed versus adaptive radius. |
| Mohajerin Esfahani & Kuhn, *Data-driven distributionally robust optimization using the Wasserstein metric*, Mathematical Programming 171 (2018) **[fetched]** | Wasserstein DRO with finite-sample performance guarantees and tractable reformulations | The benchmark any "learned uncertainty set" claim must beat. We do not attempt DRO; it is listed as the natural extension. |
| Bertsimas, Hertog, et al., *A unified theory of robust and distributionally robust optimization via the primal-worst-equals-dual-best principle*, Operations Research (2023) **[fetched]** | Unification of RO and DRO via duality | Reinforces the duality viewpoint used by the certificate: a bound is a dual object. |
| Fan, Ji, Lejeune, *Distributionally robust portfolio optimization under marginal and copula ambiguity*, JOTA 203 (2024) **[fetched]** | DRO with marginal and copula ambiguity for portfolios | Recent portfolio-specific DRO; would be the comparator for a *decision-quality* claim, which this branch does not make. |
| Rockafellar & Uryasev, *Optimization of conditional value-at-risk* (2000) **[standard]** | CVaR as a linear programme | Implemented as the `mean_cvar` baseline. |

---

## 5. Data quality, missingness and evidence provenance

| Work | Contribution | Relationship |
|---|---|---|
| Robust contextual optimisation with missing covariates (ICML 2026, PMLR 306) **[listed, not fetched]** | Robustness when covariates are missing rather than noisy | Closest formal treatment of "the input itself is degraded". Our perturbation set is a declared linear sensitivity, not a missingness model. |
| Knowledge-guided Wasserstein DRO (ICML 2025, PMLR 267) **[listed, not fetched]** | Injecting structural knowledge into the ambiguity set | The "use metadata to shape the ambiguity set" idea already exists in this line of work. Any claim that *using provenance to shape uncertainty* is new would be wrong. |
| Atlas internal: `docs/HISTORICAL_AVAILABILITY.md`, `docs/PRICE_TEMPORAL_SEMANTICS_PASS.md`, `src/atlas/evidence/kernel.py` | Four time dimensions; conservative public-as-of selection; revision lineage; no replacement of unknown availability with an earlier value | The provenance substrate this branch consumes. The two-clock revision model (`decision_as_of`, `audit_as_of`) is a deliberate extension of that contract, not a parallel one. |
| Ledoit & Wolf, *A well-conditioned estimator for large-dimensional covariance matrices*, JMVA (2004) **[standard]** | Shrinkage towards a scaled identity with analytic intensity | Implemented and differentially tested against scikit-learn. Needed because the dual bound requires a positive definite risk matrix. |

---

## 6. What is and is not claimed as new

**Not claimed as new**

1. Support-set invariancy / parametric sensitivity analysis of convex QPs.
2. Duality-gap optimality certificates.
3. KKT sufficiency for convex programs.
4. Using metadata to shape an uncertainty set.
5. Distributionally robust or conformal calibration of decision uncertainty.
6. Any new solver.

**Claimed, with the appropriate modesty**

1. **Problem formulation.** A precise audit question for decisions taken under superseded
   evidence, with a two-clock provenance model (decision clock vs audit clock) that makes
   "which revision could have influenced which decision" a checkable property rather than a
   convention. §5.4 of the technical report.
2. **A composition that yields a zero-cost certificate.** Because the dual feasible set is
   independent of the linear costs (Proposition 2), the multiplier vector recorded with a
   decision remains feasible for the corrected program; evaluating it costs one Cholesky
   solve. Combined with the exact KKT test, this gives two certificates at different cost and
   strength, and a measured statement of when each applies.
3. **An empirical characterisation with negative results.** Measured soundness (no
   violations in 598 revision events), exactness (certified events have realized regret ≤
   `1.7e-17`), a tightness gap between the free bound (median 24×) and five dual ascent steps
   (1.00×), a measured coverage curve for exact certification across position-cap tightness,
   and a **failure curve** for sensitivity misspecification (0% → 45% bound violations as the
   declared revision shrinks to one tenth of the true revision).
4. **A reusable interface** in which the same certificate operates on an operational
   capacity-allocation program with linear service floors, without portfolio vocabulary.

**The honest summary.** This is a formulation-and-systems contribution supported by
classical mathematics and a falsifiable empirical study. It is not a new theorem and it is not
a new algorithm with a novel guarantee. Whether it is publishable depends on a real-data
evaluation that this branch does not have (see the gate ledger, Gate C).

---

## 7. Evidence that would distinguish the contribution

| Claim | Distinguishing evidence | Status in this branch |
|---|---|---|
| The bound is sound | Zero violations across many revisions with independent re-solves | 598 events, 0 violations |
| The exact test is exact | Realized regret of certified decisions | max `1.68e-17` |
| The bound is useful, not vacuous | Tightness relative to realized regret, versus competitors | warm 24×, 5-step 1.00×, strong-convexity 33× |
| Provenance matters | Auditing with the wrong clock changes conclusions | hindsight arm: 1.000 apparent stability vs 0.525 actual |
| The guarantee is conditional | Violation rate as a function of misspecification | 0% → 45% |
| The method generalises | Same certificate on a second program class | sound on capacity allocation; 0% exact certification there |
| It improves *decisions* (not just audits) | Out-of-sample utility versus baselines on real data | **Not tested.** No licensed market data in this environment. |
