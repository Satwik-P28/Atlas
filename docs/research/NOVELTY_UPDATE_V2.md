# Novelty assessment, second revision

The first novelty audit was written before the worst-case extension existed and before the review
pointed at Georgia Tech ISyE's sensitivity-analysis programme. This document adds those
comparisons and restates the claim at the level the evidence actually supports. It supersedes the
*conclusions* of `PRIOR_ART_AND_NOVELTY_AUDIT.md` while leaving that document intact as the record
of what was believed at registration.

## 1. The claim, stated as narrowly as possible

> Given a decision recorded at time `t` under a convex quadratic program, and evidence published by
> audit time `τ` that is either (a) a single declared linear cost correction or (b) only known to
> lie in a documented set, one can certify an upper bound on the regret of the recorded decision
> without re-solving, using only the multipliers recorded with the decision.

Three separate things are being claimed, and they have different strengths.

| Element | Strength of claim |
|---|---|
| Formulation: regret of a *recorded* decision under evidence revisions, with a two-clock eligibility rule and revision lineage | Formulation contribution. Defensible, not provably unoccupied. |
| Composition: cost-independence of the dual feasible set makes the bound free; the residual identity makes the numerical certificate quantitative; the support function makes the set-valued case a closed form | Composition contribution. Every ingredient is classical. |
| Empirical characterisation: coverage by active-set regime, tightness-versus-iteration curve, misspecification failure curve, LP-fallback frequency, cost against a competitive solver, worst-case conservatism | Evidence contribution. This is the part a reader can use immediately, and it includes the negative results. |

Nothing in the mathematics is new. Weak duality, KKT sufficiency, support functions and
support-set invariancy analysis are all decades old, and the report says so in the abstract rather
than in a footnote.

## 2. The closest prior work, honestly

### 2.1 Support-set invariancy analysis

Ghaffari Hadigheh & Terlaky (2007) and Kheirfam (2010) compute the interval of a parameter for
which the optimal *support set* of a convex quadratic program remains invariant. The exact CRI
certificate is that test applied at a single point, asking "is the recorded support set still
optimal for the corrected program". CRI adds nothing mathematical here. What it adds is the framing
(an audit of a recorded decision, not a sensitivity study of an optimum) and the pairing with the
dual bound, which covers the 59% of events where the support set changes.

**Overlap:** high on the exact certificate. **Different:** the object certified (regret of a fixed
point rather than an invariance interval) and the pairing.

### 2.2 Parametric quadratic programming and hot starts

qpOASES (Ferreau et al., 2014) is the reference implementation of parametric active-set QP: it
solves a sequence of QPs along a parameter path by updating the working set, and the cost of a warm
re-solve is typically far below a cold one. This is the strongest practical competitor to the
certificate's cost story, and §6.8 of the report concedes the point against OSQP.

**Overlap:** the *goal* (avoid a cold re-solve). **Different:** a hot start produces a new optimal
solution and needs solver state and the full program; the certificate produces only a bound and
needs a multiplier vector. The honest statement is that a hot start is better if you want the new
optimum, and certification is cheaper only in the sense that it needs less information.

### 2.3 Sensitivity analysis for mixed-integer programs (Georgia Tech ISyE)

Dey and co-authors study how the optimal value of a mixed-integer program responds to
right-hand-side changes, using stored dual and basis information where it exists. The review
correctly pointed at this as the nearest active research programme. The relation:

* it concerns **mixed-integer** programs, where no dual bound exists in general and the analysis
  uses value functions and branching structure; CRI is confined to the continuous convex case;
* it concerns the **optimal value change**; CRI bounds the **regret of a fixed recorded point**,
  which is a different functional and is what an audit needs (a decision that was taken, not one
  that would have been taken);
* it has no analogue of the evidence-eligibility layer or of the set-valued worst case.

No claim is made that CRI is a better method than this literature. The claim is that it answers a
different question, and that the answer is cheap in the continuous case for the reason given in
Proposition 2.

### 2.4 Robust and distributionally robust optimisation

The support function is the core object of robust optimisation (Ben-Tal & Nemirovski 1999;
Bertsimas & Sim 2004; Bertsimas, den Hertog et al. 2023). Using it to bound a *fixed* decision's
worst-case regret, rather than to construct a robust decision, is a post-hoc certificate rather
than a solution method, and no novelty is claimed for the support function itself.

Distributionally robust optimisation with Wasserstein ambiguity (Mohajerin Esfahani & Kuhn 2018)
and its portfolio applications require a calibrated ambiguity set and produce a robust decision.
CRI-U takes the set as declared and *measures* what happens when the declaration is wrong
(87.5% bound violations for out-of-set corrections). It makes no coverage guarantee and is
therefore not a competitor to DRO on DRO's own ground.

**The one asymmetry worth pointing at.** In CRI-U the inner problem — maximise regret over the
uncertainty set — is *not* convex (it is a convex function maximised over a convex set, hence
NP-hard over a box), while the outer problem — minimise the bound over the multiplier — *is*
convex. Robust optimisation has the opposite structure: the inner adversarial problem is usually
the tractable one (a linear program or a conic program) and it is the robust counterpart that can
become hard. That inversion is the reason this certificate is cheap, and it is the only
methodological observation in the branch that I have not found stated in this form elsewhere.
**It is not a theorem**, it is a consequence of two expansions, and it may well be folklore.

### 2.5 Decision-focused learning and worst-case regret

Yamao et al. (UAI 2026) minimise worst-case regret during *training*; Schutte et al. (IJCAI 2024)
characterise robustness of decision-focused losses. Both are about how to *learn* a predictor whose
downstream decisions are good. CRI asks what can be said about a decision already taken. The
worst-case-regret vocabulary overlaps; the object and the timing do not.

## 3. Prior art specifically checked for the new extension

| Candidate source of the CRI-U bound | Difference |
|---|---|
| Robust counterpart of a QP | That constructs a robustly optimal `x`. CRI-U bounds the objective at a *given* `x` and never forms a counterpart. |
| Post-optimality / economic sensitivity (Fiacco 1983; Pacaud 2025) | Gives derivatives of the optimal value; a first-order estimate, not a bound. The report measures the first-order estimate understating regret in 22.6% of events. |
| Bounding the value function with duality (standard LP/QP duality) | The bound `f(w) - g(λ)` is textbook. Proposition 6 composes it with the set supremum and adds the curvature term; the composition is elementary. |
| Interval analysis / affine arithmetic | Propagates intervals through arithmetic; it does not use the dual to localise the bound, and it does not exploit the concavity of the value function in `c`. |
| Scenario optimisation over `U` | Enumerates or samples scenarios and re-solves. CRI-U does neither; §6.10 measures 52× in four dimensions and the gap is `2^n` versus `O(n^3)`. |

**Conclusion on novelty.** CRI-U is a correct composition of classical pieces. The most likely
outcome of external review is "this is robust optimisation's support function applied to a
dual bound", and that reading is fair. What is defensible is: (i) the audit framing and its
eligibility semantics, (ii) the observation that the certificate is convex in the multiplier and
non-convex in the uncertainty, so the *outer* problem is the one to optimise, and (iii) the
empirical characterisation, including the conservatism factor and the failure modes.

## 4. What would make this a stronger contribution

Listed because the honest assessment is "not yet sufficient for a strong venue", and the reasons
are specific:

1. **A real multi-firm study.** One documented SEC revenue reclassification — a conforming recast,
   not a restatement — is a pipeline demonstration. A study over a few hundred
   revenue/inventory restatements and reclassifications, with the sensitivity estimated rather
   than declared, would turn §7 into evidence.
2. **The set-valued case with a calibrated set.** CRI-U is sound but conservative; a comparison
   against a conformal or DRO-calibrated set on the same data would establish whether the
   conservatism is a modelling artefact or intrinsic.
3. **A tight curvature term.** The elementwise envelope is crude. For a box the exact supremum of a
   convex quadratic is NP-hard, but a semidefinite or spectral relaxation would likely cut the
   1.53× conservatism substantially, and would be a genuine technical contribution.
4. **A comparison against qpOASES on a path.** If the audit is one of many sequential revisions,
   the right competitor is a parametric solver, and the comparison has not been made.

None of these is attempted here. The deliverable is a correct, tested, honestly reported narrow
result, not a submission-ready paper.
