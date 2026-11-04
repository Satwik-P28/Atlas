# ADR 0015 — Versioned Universal Research Objects are contracts, not execution

**Status:** Accepted (Phase 2.1)

## Context

Atlas needs a shared vocabulary for datasets, models, experiments, strategies and
applications so research can be reviewed, reproduced and linked to evidence. The risk is
that a “research object” becomes an execution surface — stored SQL, Python or a strategy
that silently trades — bypassing the evidence kernel and its provenance guarantees.

## Decision

1. Define `atlas.research_object.v1` with five kinds: `dataset`, `model`, `experiment`,
   `strategy`, `application`.
2. Validate required fields, per-kind `spec` fields, semver versions, status and as-of
   semantics. Reject unknown top-level fields so a typo cannot silently change meaning.
3. Reject code-like keys anywhere in the document (`code`, `sql`, `python`, `javascript`,
   `executable`, `script`, `lambda`). Atlas stores declarations only; it does not execute
   them.
4. Require evidence ids to exist and link them in `research_object_evidence` with foreign
   keys. Non-application objects must cite evidence; applications may cite objects.
5. Store documents immutably by `(owner, kind, name, version)` with a SHA-256 content
   hash. A revision is a new version, matching the evidence kernel's append-only model.
6. Integrate reads with the existing reverse dependency index: object reads return
   dependent computations, and X-Ray returns research objects that cite the evidence.

## Consequences

* Research objects cannot become a second, unvalidated computation path.
* A future experiment runner must cite an object and emit evidence through the kernel,
  rather than hiding logic in the object document.
* Schema evolution requires a new `schema_version`; old documents remain readable.
* There is intentionally no simulation, backtesting or model-execution engine in this
  phase.
