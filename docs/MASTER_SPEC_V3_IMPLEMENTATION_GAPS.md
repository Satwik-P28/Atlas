# Master Specification v3 implementation gaps

Companion to `docs/MASTER_SPEC_TRACEABILITY.md` (61 requirements, machine-readable in
`artifacts/master_spec_requirements.json`) and
`docs/INSTITUTIONAL_CAPABILITY_SCOREBOARD.md` (ICB-01..48).

Method: each section was read in the canonical v3.0.0 document, then searched for in the
working tree. A section is `implemented_verified` only where a test or audit in this
repository exercises the stated behaviour; `prototype_verified` where controlled fixtures
run but production proof is absent; `vision_only` otherwise. A module with a suggestive name
is never evidence.

## 1. The eight systems

| System | State | What exists | What is missing |
| --- | --- | --- | --- |
| Financial Terminal | `implemented_verified`, partial | Canonical market series, chart, provenance, screeners, workspaces, adapters over SEC facts, responsive web UI | Multi-asset coverage (funds, FX, options, rates), live feeds, watchlists beyond a stub |
| Fundamental Research | `prototype_verified` | SEC XBRL statements, restatements, derived metrics with evidence ids, DCF and bank residual income | Three-statement build, comps bench, segment/lease/policy notes |
| Quantitative Research OS | `prototype_verified` | Point-in-time features, calibrated learning, walk-forward experiments, audits | Cost-aware backtest accounting, execution research, tournaments |
| Global OSINT Intelligence | `vision_only` | An energy/weather case study with a source-backed graph | Ingestion, entity resolution at scale, claim labelling, monitoring |
| Economic Simulation | `prototype_verified` | EIA/NOAA panel, weather-demand model, scenarios with uncertainty | Macro vintages, general equilibrium, other domains |
| Financial-Economic Compiler | `prototype_verified` | Typed IR, allowlisted operators, versioned graphs, compatibility refusal | Parsing frontends, planning/optimization passes, nested composition at scale |
| Research Operating System | `prototype_verified` | As-of cutoffs, replay pins, portable packages, saved workspaces | Project lifecycle, thesis objects, Sentinel monitoring |
| Dynamic Workspace System | `prototype_verified` | Linked workspaces and an application runtime | Adaptive workspace, cross-surface object layer |

## 2. Cross-cutting v3 contracts

| Contract | Section | State | Gap that matters |
| --- | --- | --- | --- |
| Universal Research Object System | 6 | `prototype_verified` | Envelope exists for research/app objects; the full family (models, portfolios, memos, experiments) is absent |
| Universal Model Registry and Composition | 36, 37 | `prototype_verified` | Registry is narrow; no tournament or search; composition is typed but shallow |
| Financial Knowledge Engine | 49 | `vision_only` | No chunking, index, retrieval, span grounding or abstention |
| Compression / CDG research | 50 | `vision_only` | No encoder, corpus or reconstruction test |
| Intent-to-Research Compiler | 51 | `vision_only` | No plan schema, planner or permission checker |
| Research Integrity Engine | 52 | `prototype_verified` | Model Auditor and financial audits exist; statistical and decision checks are not unified |
| Resource Optimization Engine | 53 | `vision_only` | One projection plan is measured; no policy selection |
| Data Coverage / Integrity / Service Health | 54 | `prototype_verified` | Source status, synthetic labelling, missing-session counts exist; no unified dashboard, no historical universe |
| Model Experience System | 55 | `vision_only` | No synchronized multi-view editor |
| Workflow Portability and Migration | 56 | `vision_only` | Packages are portable; spreadsheets, notebooks and memos are not |
| ResearchOS scientific programme | 57 | `vision_only` | No protocol, corpora or replication |
| Integration/dependency registry | 58 | `vision_only` | Prose document only, no licence gate |

## 3. The first flagship workflow (Section 59.1)

The target sequence is: choose a company → inspect original evidence → reconcile financial
statements → configure a model → run scenarios → challenge assumptions and coverage → export
a professional artefact → save a thesis → monitor relevant evidence changes.

| # | Step | State | How it works today | Smallest missing piece |
| --- | --- | --- | --- | --- |
| 1 | Choose a real company | **Working in the UI** | Company page resolves ticker/CIK to issuer and security with ambiguity refusal | — |
| 2 | Inspect original evidence | **Working in the UI** | Filing list, X-Ray facts with `evidence_id`, observation inspector, price provenance | Accession-level document text is not rendered |
| 3 | Reconcile financial statements | **Partial** | Points of fact reconcile against source payloads (`reconcile.py`), restatements are selectable | No statement-level reconciliation view or period-type/flow check surface |
| 4 | Configure a model | **API/script only** | DCF and bank residual income run through the FEC with versioned graphs; Studio exposes parameters | No in-UI model configuration for arbitrary models |
| 5 | Run scenarios | **Partial** | Scenario parameters and sensitivities exist for the supported models | No scenario comparison artefact or saved scenario set |
| 6 | Challenge assumptions and coverage | **Partial** | Coverage-vs-valuation readiness, model audit findings, rights warnings | No adversarial challenge workflow tied to a saved thesis |
| 7 | Export a professional artefact | **Unsupported** | Application packages and CSV exports exist; the workspace can be exported as a package | No memo/report artefact grounded in evidence ids |
| 8 | Save a thesis | **Working in the UI** | Workspaces persist research state | A thesis is a workspace, not a versioned thesis object with an evidence set |
| 9 | Monitor relevant evidence changes | **Unsupported** | Phase 7 monitoring is manual and deterministic; no scheduler or notification delivery | Dependency-aware invalidation and change reporting on a saved thesis |

**The smallest missing component that prevents an external user from completing the
workflow** is step 7: a grounded research artefact. Steps 1–6 produce verified evidence and
supported model output, and step 8 stores state, but nothing leaves the application as a
professional deliverable, and step 9 has nothing to monitor because no artefact is bound to
an evidence set.

The next milestone is therefore deliberately small: export a report whose every claim,
number and citation resolves to a stored evidence, observation or model-version id, bind it
to the saved workspace, and let a later revision mark it stale with the affected items
listed. That is ICB-48's prerequisite and it requires no new retrieval engine, no new
database and no new evidence store.

## 4. What this analysis does not claim

* No section is `production_eligible`; no security, rights, performance and operating gate
  set has been run for a named scope.
* `prototype_verified` is not "working for users": it means controlled fixtures run here.
* The absence of a module is reported as absence, not as a partial implementation.
