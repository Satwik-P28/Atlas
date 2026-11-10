# Master specification traceability

Status: **received_integrity_verified** — the canonical v3.0.0 document is present and
byte-verified. This proves the document's identity, not implementation conformance.

## Canonical specification

| Property | Verified value |
| --- | --- |
| File | `ATLAS_MASTER_SPEC.md` (repository root) |
| Version | 3.0.0 |
| Date | 2026-11-09 |
| Size | 289,963 bytes |
| SHA-256 | `c1228db93e66a04fb211bea85f6c978289a6040b1f655f934da76498c8c4752d` |
| Sections | 1–61 (all present) |
| Integrity verified | 2026-11-10 by `scripts/verify_master_spec.py` |
| Verification commit | `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

Reproduce:

```bash
python scripts/verify_master_spec.py
sha256sum ATLAS_MASTER_SPEC.md
python scripts/build_master_spec_registries.py
python scripts/render_spec_registries.py
python -m pytest tests/test_phase9_2_8_master_spec_registry.py
```

## What the status means

Statuses use only the Section 60.2 publication vocabulary. `internally_partial` is a
planning flag recorded beside the status, never a replacement for it.

- `vision_only` — Specified, no verified implementation. Also used for normative charter and process sections that are not capabilities.
- `implemented_unverified` — Code exists but no executed acceptance evidence was found at this revision.
- `prototype_verified` — Runs controlled fixtures and tests in this repository; insufficient production proof.
- `implemented_verified` — Exercised by repository tests against the stated acceptance cases at this revision.
- `production_eligible` — Passed security, correctness, rights, performance and operating gates for a named scope. Not claimed for any requirement.
- `deprecated_or_invalidated` — Superseded, disabled or failed a required contract.

A capability is not marked implemented because a module or class of similar name exists.
A benchmark is not marked passed because unit tests are green. Nothing in this repository
reaches `production_eligible`: that requires security, correctness, data-rights, performance
and operating gates for a named scope, and none has been run.

## Counts

61 requirements mapped across 61 canonical sections (25 internally recorded as partial).

| Status | Requirements |
| --- | --- |
| `vision_only` | 30 |
| `prototype_verified` | 22 |
| `implemented_verified` | 9 |

## Requirement matrix

Machine-readable source: `artifacts/master_spec_requirements.json`.

| ID | § | Section | Subsystem | Status | Partial | Evidence | Unimplemented dependency | Sev | Pri |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MS3-01 | 1 | Mission, positioning, and the standard of success | Platform charter | `vision_only` | no | README.md states the open-core position. | A standing goal, not a testable capability; conformance is measured through Sections 5-61. | medium | P3 |
| MS3-02 | 2 | Product model: Eight integrated systems, one experience | Platform architecture | `prototype_verified` | yes | Six of the eight systems have running code and tests. | Atlas Intelligence and OSINT exist only as partial or absent systems. | high | P2 |
| MS3-03 | 3 | Interface: almost limitless depth with minimal visible clutter | Frontend | `prototype_verified` | yes | The React terminal exposes the four root spaces with linked workspaces. | Studio, Lab and Monitor are thin; depth exists mainly for the terminal surface. | medium | P3 |
| MS3-04 | 4 | Replaceability and competition | Strategy | `vision_only` | no | README.md documents positioning. | No independent competitive benchmark has been executed. | low | P4 |
| MS3-05 | 5 | Architecture: the unified financial computing substrate | Platform architecture | `prototype_verified` | yes | Identity, evidence kernel, compiler subset and SQLite storage exist and are tested. | Adaptive workspace and cross-surface object layer are partial. | high | P2 |
| MS3-06 | 6 | Universal Research Object System (UROS) | Research objects | `prototype_verified` | yes | Versioned research objects with manifests and lineage exist for research and application paths. | The full object-family catalogue (models, apps, portfolios, memos) is not implemented. | high | P1 |
| MS3-07 | 7 | Data Fabric, Temporal Evidence Kernel, and source quality | Evidence | `implemented_verified` | no | Reference database holds 26,440 evidence records; differential Python/SQL selection test passes. | Cross-source quality scoring is partial (Section 54). | high | P1 |
| MS3-08 | 8 | Financial-Economic Ontology and entity graph | Ontology | `prototype_verified` | yes | Issuer/security/listing/ticker identity with ambiguity refusal is implemented and tested. | Event, contract and forecast objects exist only as written contracts. | medium | P3 |
| MS3-09 | 9 | Data Rights Engine and sustainable open-source economics | Data rights | `implemented_verified` | no | Rights violations are refused by tests; restricted sources are labelled as restricted. | Rights-aware query planning across all feeds is partial. | critical | P1 |
| MS3-10 | 10 | Financial-Economic Compiler: the central original engineering asset | Compiler | `prototype_verified` | yes | Allowlisted operators, versioned graphs and refusal on contract mismatch are tested. | Parsing frontends, dependency planning and optimisation passes are partial. | high | P2 |
| MS3-11 | 11 | Universal Execution Runtime and storage/compute architecture | Runtime | `prototype_verified` | yes | SQLite/NumPy execution with recorded jobs exists. | No multi-engine scheduler, job queue or distributed execution. | medium | P3 |
| MS3-12 | 12 | Model Forge: unrestricted model creativity with enforced contracts | Models | `prototype_verified` | yes | Registered models and versioned graphs execute with declared coverage. | Visual authoring and an invention sandbox are absent. | high | P2 |
| MS3-13 | 13 | Quant Lab, Alpha Foundry, and historical strategy simulation | Quant research | `prototype_verified` | yes | Walk-forward experiments with leakage guards and audit records are tested. | Full backtest accounting (cash, positions, costs) is not implemented. | high | P2 |
| MS3-14 | 14 | Institutional valuation, fixed income, derivatives, and portfolio risk | Institutional finance | `prototype_verified` | yes | Bank residual income v2/v3 pass independent audits 29/29 and 16/16; DCF component checks pass. | Fixed income, derivatives and portfolio risk are unimplemented. | critical | P1 |
| MS3-15 | 15 | Atlas Intelligence: a real brain, not a mandatory chatbot | Intelligence | `prototype_verified` | yes | Model selection, calibration and audit records run offline. | Research planner, meta-learning and contextual services are absent; no LLM integration. | medium | P3 |
| MS3-16 | 16 | Global OSINT, news intelligence, and the Economic Reality Engine | OSINT | `vision_only` | no | Only the Phase 7 energy/weather case study exists as a thin economic slice. | No OSINT ingestion, entity linking or claim labelling. | medium | P3 |
| MS3-17 | 17 | Research Operating System, Time Capsule, and Sentinel | Research OS | `prototype_verified` | yes | Information cutoffs, as-of selection and observation replay are implemented and tested. | Project lifecycle objects, Sentinel monitoring and Time Capsule export are partial. | high | P2 |
| MS3-18 | 18 | Financial Application Compiler and plugin ecosystem | Applications | `implemented_verified` | no | Declarative packages build, install, execute, fork and reproduce from a clean install. | The Intent-to-Workspace frontend and a third-party plugin sandbox are absent. | high | P2 |
| MS3-19 | 19 | API, SDK, scripting, and extension contracts | API | `implemented_verified` | yes | Typed FastAPI surface with stable operation ids, error envelopes and a saved OpenAPI baseline. | No published SDK, scripting bridge or extension packaging. | high | P2 |
| MS3-20 | 20 | Security, privacy, safety, and operational governance | Security | `implemented_verified` | yes | Body limits, archive bounds and zip-bomb defences are tested. | No multi-tenant isolation, audit log or secrets management; operation remains loopback-only. | critical | P1 |
| MS3-21 | 21 | Stack evolution and implementation discipline | Engineering process | `implemented_verified` | no | Phase acceptance documents record verification limits; dependency contract tests pass. | No open gap recorded. | medium | P3 |
| MS3-22 | 22 | Institutional Capability Benchmark (ICB) | Benchmarks | `prototype_verified` | yes | Repository benchmarks and audits exist and are reproducible for their declared scope. | Most ICB suites have never been executed; see artifacts/icb_registry.json. | high | P1 |
| MS3-23 | 23 | Development roadmap, priorities, and release gates | Roadmap | `vision_only` | no | Phase 9.2.x acceptance documents record gates and blockers. | No specification-aligned roadmap existed before this checkpoint. | high | P0 |
| MS3-24 | 24 | Architecture decision record and contribution governance | Governance | `implemented_verified` | no | ADRs 0001-0003 exist for storage, identity and analytics. | No formal review or maintainer process. | low | P4 |
| MS3-25 | 25 | Strategic risks and mitigation | Risk | `vision_only` | no | Risk themes appear in distribution and beta documentation. | No consolidated, maintained risk register. | medium | P3 |
| MS3-26 | 26 | Canonical end-to-end research demonstrations | Product workflow | `prototype_verified` | yes | Valuation and provenance steps run against SEC fixtures and are browser-tested for desktop. | Evidence reconciliation and narrative retrieval in Demonstration A are missing. | high | P1 |
| MS3-27 | 27 | Research source and software inventory | Dependencies | `vision_only` | no | A prose dependency evaluation document exists. | No machine-checked licence registry (Section 58). | low | P4 |
| MS3-28 | 28 | Instructions for all future Atlas engineering agents | Engineering process | `implemented_verified` | no | Status vocabulary and evidence discipline applied here. | No open gap recorded. | medium | P3 |
| MS3-29 | 29 | Expansion decision and domain boundaries | Strategy | `vision_only` | no | Only the specification defines this boundary. | No event-market capability exists. | low | P4 |
| MS3-30 | 30 | Universal Event and Probability Engine | Events | `vision_only` | no | None. | No event, contract or settlement implementation. | medium | P3 |
| MS3-31 | 31 | Causal, decision, and opportunity intelligence | Causal research | `vision_only` | no | Design document only. | No causal estimation code. | medium | P3 |
| MS3-32 | 32 | Domain packs, implementation gates, and event benchmarks | Domain packs | `prototype_verified` | yes | A domain pack ships, installs and executes on the unchanged substrate. | Event-domain packs and ICB-11..18 are not implemented. | medium | P3 |
| MS3-33 | 33 | Atlas Real Estate Investment Intelligence | Real estate | `vision_only` | no | Specification only. | No real estate ontology, lease model or geographic joins. | low | P4 |
| MS3-34 | 34 | Platform constitution: the universal financial operating system | Charter | `vision_only` | no | Positioning only. | No conformance mechanism defined. | low | P4 |
| MS3-35 | 35 | Users, complete jobs and adoption-critical workflows | Product | `vision_only` | no | A role matrix and beta plan exist. | No role-complete workflow has been demonstrated end to end. | high | P2 |
| MS3-36 | 36 | Universal investment model library and coverage contracts | Model registry | `prototype_verified` | yes | Registered models execute with declared coverage; DCF and bank residual income are audited. | The catalogue covers a small fraction of the specified model families. | high | P2 |
| MS3-37 | 37 | Model composition, invention and computational research | Model composition | `prototype_verified` | yes | Nested versioned graphs execute with schema checks and refusal on mismatch. | Tournament, invention sandbox and model search are absent. | high | P2 |
| MS3-38 | 38 | Global financial terminal and market intelligence | Market terminal | `implemented_verified` | yes | Canonical series contract with provider identity, revisions, rights and a bounded overview projection. | Only listed equities with daily bars are covered; no funds, FX, options or live feeds. | high | P1 |
| MS3-39 | 39 | Equity, fundamental, accounting and research desk | Fundamentals | `prototype_verified` | yes | SEC XBRL statements, restatement handling and derived metrics with provenance are tested. | Segments, leases and accounting-policy notes are absent. | high | P1 |
| MS3-40 | 40 | Quantitative trading, strategy science and execution research | Quant research | `prototype_verified` | yes | Walk-forward experiments with as-of data and audit are tested. | No execution simulation, transaction-cost model or broker integration. | medium | P3 |
| MS3-41 | 41 | Institutional portfolio management, risk and operations | Portfolio operations | `vision_only` | no | None. | No position, order or portfolio accounting implementation. | high | P2 |
| MS3-42 | 42 | Investment banking and transaction intelligence | Investment banking | `vision_only` | no | None. | No banking workflow beyond the bank valuation model. | medium | P3 |
| MS3-43 | 43 | Venture capital, private equity, private credit and fund intelligence | Private markets | `vision_only` | no | None. | No private-market data model or fund mathematics. | medium | P4 |
| MS3-44 | 44 | Personal finance, wealth and consumer decision support | Consumer | `vision_only` | no | None. | No accounts, planning or consent model. | medium | P3 |
| MS3-45 | 45 | Adaptive experience, human factors and professional workflow design | UX | `vision_only` | no | Navigation exists; adaptivity does not. | No progressive disclosure or accessibility certification. | medium | P3 |
| MS3-46 | 46 | Quant Stack compatibility and migration contract | Migration | `vision_only` | no | None. | No importer, compatibility fixture or parity report. | medium | P3 |
| MS3-47 | 47 | Enterprise, institutions, connectivity and deliverable interoperability | Interoperability | `vision_only` | no | None. | No Excel or notebook export. | medium | P3 |
| MS3-48 | 48 | Release strategy, external benchmarks and ecosystem growth | Release | `vision_only` | no | Release gates are documented for Phase 9.2.x only. | No external benchmark programme; ICB-21..32 have not been executed. | high | P2 |
| MS3-49 | 49 | Financial Knowledge Engine: unified, evidence-preserving retrieval | Knowledge engine | `vision_only` | no | None. | No retrieval layer; the integration contract is docs/RESEARCH_AND_COMPRESSION_INTEGRATION.md. | high | P2 |
| MS3-50 | 50 | Compression, CDG and evidence-preserving data research | Compression research | `vision_only` | no | None; hypotheses only. | No encoder, corpus or reconstruction test. | medium | P3 |
| MS3-51 | 51 | Intent-to-Research Compiler and adaptive workflows | Intent compiler | `vision_only` | no | None. | No planner, plan schema or permission checking. | high | P2 |
| MS3-52 | 52 | Research Integrity Engine: evidence, mathematics and decisions | Integrity | `prototype_verified` | yes | Model Auditor and independent financial audits produce per-check findings. | Statistical-validity and decision-level checks are not part of a unified report. | high | P1 |
| MS3-53 | 53 | Atlas Resource Optimization Engine: the industrial engineering core | Resource optimization | `vision_only` | no | None. | No policy engine or cost model. | medium | P3 |
| MS3-54 | 54 | Data Coverage, Integrity and Service Health Center | Data health | `prototype_verified` | yes | Source status, synthetic labelling, missing-session counts and coverage blocks are surfaced. | No unified coverage, freshness and conflict dashboard; no historical universe reporting. | high | P2 |
| MS3-55 | 55 | Model Experience System and adaptive human-computer interaction | Model UX | `vision_only` | no | None. | No synchronized multi-view editor. | medium | P4 |
| MS3-56 | 56 | Workflow Portability, Migration and Professional Deliverables | Portability | `vision_only` | no | Application packages are portable; spreadsheets and documents are not. | No spreadsheet, notebook or document import or export. | medium | P3 |
| MS3-57 | 57 | ResearchOS scientific program for AI, RAG, compression and IE | Research programme | `vision_only` | no | None. | No experiment protocol, corpus or replication study. | medium | P3 |
| MS3-58 | 58 | Open-source integration and dependency evaluation registry | Dependencies | `vision_only` | no | A prose evaluation document exists. | No machine-readable registry or licence gate. | low | P4 |
| MS3-59 | 59 | Product delivery sequence and cross-domain user adoption | Delivery | `prototype_verified` | yes | Company, statements, model, scenarios, provenance and saved workspace run end to end; see docs/MASTER_SPEC_V3_IMPLEMENTATION_GAPS.md. | Narrative evidence retrieval, professional export and monitoring are missing; this is the smallest blocking gap. | critical | P0 |
| MS3-60 | 60 | New Institutional Capability Benchmarks and acceptance matrix | Benchmarks | `vision_only` | no | ICB-01..48 registry built with statuses and evidence gaps; no v3 benchmark has been executed. | ICB-33..48 are specified only. | high | P1 |
| MS3-61 | 61 | Final platform definition and strategic charter | Charter | `vision_only` | no | Charter only. | A judgement criterion, not a testable capability. | low | P4 |

## Historical record, preserved

Earlier checkpoints (`docs/MASTER_SPEC_TRACEABILITY.md` before this revision and
`docs/MASTER_SPEC_GATE.md`) correctly reported that the then-expected v1.2.0 document
(155,419 bytes, SHA-256 `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`)
was absent, and refused to map requirements from an invented copy. Those reports were
accurate for their checkpoints and are not rewritten here. The current canonical document
is v3.0.0 at the size and hash above; the v1.2 hash must not be presented as matching it.

The earlier statement that "the only ICB identifiers defined anywhere in this repository are
ICB-04 and ICB-09" was also correct at that time: ICB-01 through ICB-48 are now read from
the canonical document and registered in `artifacts/icb_registry.json`.
