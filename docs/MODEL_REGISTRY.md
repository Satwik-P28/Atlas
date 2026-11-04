# Model registry and research objects

Schema: `atlas.research_object.v1`. Existing kinds are preserved; `financial_metric` is
added. Objects are immutable versions: creating a changed model requires a new version.

## Lifecycle

`create → validate → version → execute → inspect → fork → compare → export`

- **create** validates the document and evidence/object/source references.
- **execute** is available for `model` objects containing a canonical `model_spec`.
- **fork** deep-copies the document under a new name/version and records
  `spec.forked_from`; the source object is untouched.
- **compare** returns structural changes and both content hashes.
- **export** writes a reproducibility manifest with the document, evidence links,
  dependency object hashes, compiler and operator versions.

Applications reference model/dataset object ids rather than embedding untracked results.

## Storage

`research_object` and `research_object_evidence` (migration 004) remain authoritative.
No execution result is written as evidence. `model_run` stores execution records;
`research_object` stores the declarative definition.

## Explicit gaps

Strategy and simulation execution boundaries are reserved but not implemented. Model
versions are immutable, but automatic semver selection and provenance-preserving schema
upgrades are not yet implemented.
