# Master specification traceability

## Status: BLOCKED

The canonical document is not available to this checkpoint.

| Property | Declared value |
| --- | --- |
| Filename | `ATLAS_MASTER_SPEC.md` |
| Expected bytes | `155419` |
| Expected SHA-256 | `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9` |
| Present in checkout | no |
| `scripts/verify_master_spec.py` | exit 1, `BLOCKED: ATLAS_MASTER_SPEC.md is not present` |

The document was **not** regenerated from a prompt, reconstructed from its checksum, or
approximated from memory. A filename and a hash are not a specification, and mapping
requirements from an invented copy would produce a traceability matrix that looks complete
and proves nothing.

No requirement in this file is attributed to the master specification until the genuine
document is present and verified at the declared size and hash.

## What this file does instead

It records the requirements this repository can actually verify today, so the gap between
claim and evidence stays visible. These are Atlas's own phase acceptance criteria, taken from
the tracked documentation and executable checks — not master-spec clauses.

| Requirement (source) | Behaviour | Modules | Evidence | Status |
| --- | --- | --- | --- | --- |
| Immutable source records (`docs/EVIDENCE_RECONCILIATION.md`) | stored raw documents with SHA-256 and retrieval metadata | `atlas/ingestion`, `atlas/storage` | 26,440 evidence records in the reference database; `tests/test_phase9_2_migrations.py` | Implemented, locally tested |
| Exact observation identity and replay (`docs/MARKET_DATA_AND_RIGHTS.md`) | `observation_id`, revision chain, pin replay, no substitution | `atlas/research/observations.py`, `atlas/research/prices.py` | `tests/test_phase9_2_3_acceptance.py`; browser B2–B6 | Implemented, browser-verified |
| Data rights fail closed (`docs/DATA_RIGHTS_AND_DISTRIBUTION.md`) | unknown grant rejected; redistribution distinct from copyright licence | `atlas/research/rights.py`, `atlas/applications/rights.py` | `tests/test_phase9_2_3_acceptance.py`, `tests/test_phase9_2_2_data_rights_fixtures.py` | Implemented, locally tested |
| Bank common-equity valuation (`docs/BANK_VALUATION_V2.md`) | SEC common equity, average-common ROE, residual income, FCFF refused | `atlas/research/equity.py`, `atlas/finance` | 29/29 and 16/16 independent audits; browser A1–A5 | Implemented, independently audited |
| Portable research applications (`docs/APPLICATION_PACKAGE_SPEC.md`) | deterministic ZIP, declarative only, install/execute/fork | `atlas/applications` | clean-install reproduction; `tests/test_phase8_applications.py` | Implemented, locally tested |
| No bundled market prices | unavailable comparison is explicit, never fabricated | `atlas/research/prices.py` | browser A2; `tests/test_phase9_2_4_acceptance.py` | Implemented, browser-verified |
| Synthetic data is labelled synthetic | source kind follows the collection method | `atlas/research/prices.py`, `atlas/terminal/read_models.py` | `tests/test_phase9_2_4_acceptance.py`; browser B1 | Implemented, browser-verified |
| Clean-checkout operation | declared dependencies are sufficient; fixtures reproduce | `pyproject.toml`, `scripts/` | `tests/test_packaging_contract.py`; clean virtual environments | Implemented, locally tested |
| CI execution | workflow runs on a hosted runner | `.github/workflows/ci.yml` | not observed (private repository, no Actions credential) | Blocked |
| Master specification conformance | every clause mapped and verified | — | — | Blocked |

## Phase 9.2.5 re-check

The document is still absent (`find / -name 'ATLAS_MASTER_SPEC*'` returns nothing), so the
status is unchanged: **zero clauses mapped**, no 34-section review, no ICB mapping. The
only ICB identifiers defined anywhere in this repository are ICB-04 and ICB-09, referenced
in `docs/PHASE7_READINESS.md`; ICB-01…ICB-20 cannot be mapped without inventing eighteen
definitions, which this project will not do.

Implementation coverage below is therefore **repository-verifiable capability**, not
specification conformance. It is stated by subsystem so a later clause review has a
starting point that is already honest.

| Subsystem | Implemented capability | Evidence | State |
| --- | --- | --- | --- |
| Temporal evidence | immutable raw documents, point-in-time selection, supersession, provenance | 26,440 evidence rows; differential Python/SQL test; `tests/test_evidence.py` | implemented locally tested |
| Identity | issuer → security → listing → ticker with ambiguity refusal | `tests/test_entities.py`, `tests/test_multi_issuer.py` | implemented locally tested |
| Market data | revisions, calendars, adjustments, observation pins, rights | `tests/test_market.py`, `tests/test_phase9_2_3_acceptance.py` | implemented locally tested |
| Equity research | DCF with eight component checks; bank residual income v3 | audits 29/29 and 16/16; browser A1–A5 | implemented independently audited |
| Financial institution evidence | FR Y-9C parent consolidated, FDIC subsidiary separated | `tests/test_phase9_2_fr_y9c.py` | implemented locally tested |
| Model runtime | allowlisted FEC operators, versioned graphs, execution refusal on mismatch | `tests/test_fec.py`, `tests/test_phase9_1_models.py` | implemented locally tested |
| Learning | dataset eligibility (60-session minimum), experiments, audit | `tests/test_phase6_learning.py` | implemented locally tested |
| Economic case study | EIA/NOAA panel, weather-demand model, scenarios | `tests/test_phase7_economic.py` | implemented locally tested |
| Applications | declarative packages, install/execute/fork, domain packs, rights | `tests/test_phase8_applications.py`, clean-install reproduction | implemented locally tested |
| Terminal | typed API, workspaces, provenance panel | browser journeys at `481cd58`; not re-run in 9.2.5 | implemented browser verified (9.2.4) |
| Transport hardening | bounded/complete compressed responses, bounded bodies | `tests/test_release_security_9_2_5.py` | implemented locally tested |
| Hosted CI | workflow committed, never observed | — | blocked |
| Master specification | — | — | blocked |

## Unblocking requirements

1. The genuine `ATLAS_MASTER_SPEC.md` bytes (155,419 bytes, SHA-256
   `e54c5973…4ba5c9`) placed at the repository root and verified by
   `python scripts/verify_master_spec.py`.
2. A GitHub credential with Actions read access, or a human reading the run for the pushed
   SHA, to replace the unobserved CI status with an observed one.

Until both exist, Atlas's documented position stands: the master-spec gate is **blocked**,
and Phase 9 completion is not claimed.
