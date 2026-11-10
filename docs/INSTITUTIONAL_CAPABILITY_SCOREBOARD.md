# Institutional capability scoreboard

ICB-01 through ICB-48 as defined by the canonical v3.0.0 specification (Sections 22, 48
and 60). Machine-readable source: `artifacts/icb_registry.json`.

## Acceptance rule

A benchmark is accepted only when its stated test was actually executed and the result is reproducible. Passing unit tests, a green model-arithmetic audit or a screenshot do not establish that the professional workflow was independently validated.

Consequences applied here:

- A benchmark is `prototype_verified` only where a named test or audit in this repository
  exercises the stated acceptance case; that still does not establish the professional
  workflow was independently validated.
- A model audit that checks arithmetic supports a benchmark; it does not accept it.
- No benchmark is marked executed in Phase 9.2.8. Nothing here is `production_eligible`.
- Suites that require licensed market data, exchange products or broker access are marked
  `vision_only` and are blocked on entitlement, not on engineering alone.

## Summary

Total benchmarks: 48.

| Status | Count |
| --- | --- |
| `vision_only` | 30 |
| `prototype_verified` | 18 |

## Priority order

| Priority | Benchmarks |
| --- | --- |
| P0 | ICB-01, ICB-48 |
| P1 | ICB-06, ICB-07, ICB-10, ICB-24, ICB-33, ICB-39 |
| P2 | ICB-02, ICB-03, ICB-05, ICB-17, ICB-21, ICB-22, ICB-29, ICB-31, ICB-32, ICB-34, ICB-38, ICB-41, ICB-42, ICB-46 |
| P3 | ICB-04, ICB-09, ICB-11, ICB-12, ICB-14, ICB-15, ICB-16, ICB-23, ICB-25, ICB-26, ICB-28, ICB-30, ICB-35, ICB-36, ICB-37, ICB-40, ICB-43, ICB-44, ICB-45, ICB-47 |
| P4 | ICB-08, ICB-13, ICB-18, ICB-19, ICB-20, ICB-27 |

## ICB-01 to ICB-48

### ICB-01 — Equity Research

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P0 |
| Specification | v3.0.0, Section 22 |
| Objective | SEC data to three-statement model, reverse DCF, comparables and scenario view. |
| Input dataset | SEC XBRL company facts and filings for a covered issuer (fixtures/sec). |
| Legal data entitlement | public_domain (SEC EDGAR fair access). |
| Independent baseline | Independently recomputed accounting identities and a spreadsheet reference for one issuer. |
| Required outputs | Statement model, reverse DCF, comps table, scenarios, provenance for every input. |
| Acceptance criteria | Accounting identities, period selection, filing provenance, numerical reproducibility, scenario sensitivity. |
| Existing tests | `tests/test_phase9_equity.py`, `scripts/audit_phase9_2_models.py`, `scripts/audit_phase9_financials.py` |
| Adversarial cases | Restatement in the model window; missing tag in one period; fiscal-year mismatch; zero-volume price date. |
| Evidence available | Bank residual-income v2/v3 audited 29/29 and 16/16; DCF component checks pass; three-statement and comps steps absent. |
| Missing implementation | Three-statement build, reverse DCF, comparable set and scenario export. |
| Dependencies | MS3-14, MS3-39 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-02 — Fixed Income/Risk

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P2 |
| Specification | v3.0.0, Section 22 |
| Objective | Build a curve, value bonds and vanilla rate instruments, compute sensitivities and stress. |
| Input dataset | Published test vectors and a compatible QuantLib/ORE reference case. |
| Legal data entitlement | public domain test vectors. |
| Independent baseline | QuantLib or ORE on the same inputs and curves. |
| Required outputs | Curve, prices, DV01/duration/convexity, stress results and method disclosure. |
| Acceptance criteria | Match references within declared tolerances. |
| Existing tests | none |
| Adversarial cases | Curve inversion, negative rates, distressed spread, day-count mismatch. |
| Evidence available | Curve and bond pricing primitives exist in `atlas/institutional/service.py`; coverage is incomplete rather than absent. |
| Missing implementation | Published-vector parity, derivative breadth, stress engine and day-count edge cases. |
| Dependencies | MS3-14 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-03 — Quant ML

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P2 |
| Specification | v3.0.0, Section 22 |
| Objective | Build factors, train statistical and neural baselines, run a point-in-time backtest. |
| Input dataset | Point-in-time features and prices from the canonical market series. |
| Legal data entitlement | project_authored synthetic or licensed vendor data with declared rights. |
| Independent baseline | Naive and linear baselines with identical splits. |
| Required outputs | Factors, trained model, validation metrics, backtest with costs and cash accounting. |
| Acceptance criteria | No future leakage; selection history; reproducible results. |
| Existing tests | `tests/test_phase6_learning.py` |
| Adversarial cases | Regime shift, survivorship universe, label overlap, feature revision after cutoff. |
| Evidence available | Walk-forward experiments, calibration and contamination audit are tested; no backtest accounting. |
| Missing implementation | Cash/position accounting, transaction costs, full backtest report. |
| Dependencies | MS3-13, MS3-40 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-04 — Economic Intelligence

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P3 |
| Specification | v3.0.0, Section 22 |
| Objective | Public energy or infrastructure signal to a linked issuer and modelled financial outcomes. |
| Input dataset | EIA/NOAA series plus issuer filings. |
| Legal data entitlement | public_domain. |
| Independent baseline | Deterministic re-derivation of the demand model from the same panel. |
| Required outputs | Signal, entity link, demand model, financial translation, assumptions and uncertainty. |
| Acceptance criteria | Every edge source-backed or explicitly inferred; assumptions and uncertainty shown. |
| Existing tests | `tests/test_phase7_economic.py` |
| Adversarial cases | Missing weather station, revised EIA vintage, weak entity link. |
| Evidence available | The Phase 7 energy/weather case study runs offline with documented baselines. |
| Missing implementation | Broader OSINT ingestion and entity linking. |
| Dependencies | MS3-16 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-05 — Application Creation

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P2 |
| Specification | v3.0.0, Section 22 |
| Objective | Describe and build a model-based application through code, canvas and application paths. |
| Input dataset | A declarative application package plus its model graph. |
| Legal data entitlement | project_authored. |
| Independent baseline | The same computation executed through the Python API. |
| Required outputs | Equivalent outputs through all paths; save, restart, export and restore. |
| Acceptance criteria | Same outputs through code, visual canvas and application. |
| Existing tests | `tests/test_phase8_applications.py` |
| Adversarial cases | Package with a rights-restricted input; unsupported operator; corrupt archive. |
| Evidence available | Packages build, install, execute, fork and reproduce from clean install. |
| Missing implementation | Visual canvas authoring path. |
| Dependencies | MS3-18, MS3-55 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-06 — Time Machine

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P1 |
| Specification | v3.0.0, Section 22 |
| Objective | Reconstruct company knowledge before and after an amendment and a macro revision. |
| Input dataset | Archived restatement fixtures and revisioned macro vintages. |
| Legal data entitlement | public_domain. |
| Independent baseline | Point-in-time SQL selection independent of the Python path. |
| Required outputs | As-of statements, the facts excluded and the precision available. |
| Acceptance criteria | Historical outputs exclude subsequent facts; missing precision identified. |
| Existing tests | `tests/test_history.py`, `tests/test_evidence.py` |
| Adversarial cases | Amendment filed same day; unavailable availability_time; superseded chain. |
| Evidence available | Differential Python/SQL as-of selection test passes; observation replay passes. |
| Missing implementation | Macro vintage storage and UI time machine controls. |
| Dependencies | MS3-7, MS3-17 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-07 — Data Rights

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P1 |
| Specification | v3.0.0, Section 22 |
| Objective | Build and export an application mixing public and restricted sources. |
| Input dataset | Public SEC fixtures plus a restricted vendor series. |
| Legal data entitlement | public_domain + restricted. |
| Independent baseline | Manual inspection of the exported artefact against the rights manifest. |
| Required outputs | Application, export bundle, rights report and attribution. |
| Acceptance criteria | Block unauthorised raw redistribution; preserve provenance and attribution. |
| Existing tests | `tests/test_phase9_2_3_acceptance.py`, `tests/test_phase9_2_2_data_rights_fixtures.py` |
| Adversarial cases | Unknown licence; redistributable derived metric from restricted raw data; nested package. |
| Evidence available | Rights failures are refused by tests; restricted sources are labelled. |
| Missing implementation | Cross-format export (documents, spreadsheets). |
| Dependencies | MS3-9 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-08 — GPU/CPU

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P4 |
| Specification | v3.0.0, Section 22 |
| Objective | Factor creation, neural training, Monte Carlo and screeners on realistic datasets. |
| Input dataset | Benchmark datasets sized for CPU and GPU. |
| Legal data entitlement | project_authored. |
| Independent baseline | Published CPU-only baseline with identical numerics. |
| Required outputs | Throughput, latency, memory, parity results and hardware disclosure. |
| Acceptance criteria | Publish metrics, parity tests and transfer overhead. |
| Existing tests | none |
| Adversarial cases | GPU unavailable; numerical drift; memory exhaustion. |
| Evidence available | Only CPU NumPy paths exist and none is benchmarked against a GPU. |
| Missing implementation | GPU execution and a published performance report. |
| Dependencies | MS3-11 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-09 — OSINT Research

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 22 |
| Objective | Investigate contracts, events and corporate relationships from open sources. |
| Input dataset | Legally usable public documents and registries. |
| Legal data entitlement | public_domain. |
| Independent baseline | Source-by-source manual verification of each claim. |
| Required outputs | Claim graph with observed/inferred/model-generated labels and lineage. |
| Acceptance criteria | Distinguish claim classes and preserve source and date lineage. |
| Existing tests | none |
| Adversarial cases | Conflicting reports; retracted claim; forged document. |
| Evidence available | No OSINT pipeline exists. |
| Missing implementation | Ingestion, claim extraction and labelled graph. |
| Dependencies | MS3-16 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-10 — Full Reproduction

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P1 |
| Specification | v3.0.0, Section 22 |
| Objective | Re-run an archived research application with its preserved inputs. |
| Input dataset | A committed application package and its pinned inputs. |
| Legal data entitlement | project_authored. |
| Independent baseline | Byte or value comparison against the archived declared outputs. |
| Required outputs | Reproduced outputs and an explanation of any difference. |
| Acceptance criteria | Reproduce declared deterministic outputs or explain differences. |
| Existing tests | `scripts/reproduce_phase9_2.py`, `scripts/verify_clean_install.py` |
| Adversarial cases | Missing dependency version; changed fixture; different locale/timezone. |
| Evidence available | Clean-install reproduction and reference package reproduction run offline. |
| Missing implementation | Reproduction for v3 workflows beyond the Phase 9 package. |
| Dependencies | MS3-18 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-11 — Event Semantics

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 22 |
| Objective | Parse two same-headline contracts with different settlement rules. |
| Input dataset | Contract rule texts. |
| Legal data entitlement | public domain rule text where lawful. |
| Independent baseline | Human-adjudicated rule comparison. |
| Required outputs | Rule hash, source, time, adjudicator, exceptions and payoff states. |
| Acceptance criteria | Reject false equivalence; preserve rule text hash. |
| Existing tests | none |
| Adversarial cases | Ambiguous rule; changed adjudicator; disputed settlement. |
| Evidence available | No event or contract model. |
| Missing implementation | Contract ontology and settlement semantics. |
| Dependencies | MS3-30 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-12 — Calibration and Forecast Replay

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 22 |
| Objective | Issue forecasts before outcomes and grade them after settlement. |
| Input dataset | Forecast and outcome records with as-issued timestamps. |
| Legal data entitlement | project_authored. |
| Independent baseline | Climatology and base-rate forecasts. |
| Required outputs | Brier/log/CRPS scores, reliability plots, vintage isolation. |
| Acceptance criteria | Correct scoring and no as-issued vintage contamination. |
| Existing tests | none |
| Adversarial cases | Missing outcome; revised vintage; class imbalance. |
| Evidence available | No forecast store or scoring service. |
| Missing implementation | Forecast ledger and scoring. |
| Dependencies | MS3-30 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-13 — Market Feasibility

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P4 |
| Specification | v3.0.0, Section 22 |
| Objective | Compare simulated payoff with market quotes. |
| Input dataset | Venue quotes with fees and depth. |
| Legal data entitlement | requires licensed data. |
| Independent baseline | Quote-based executable-fill model. |
| Required outputs | Payoff, quotes, fees, depth and uncertainty. |
| Acceptance criteria | Never imply an executable fill from mids. |
| Existing tests | none |
| Adversarial cases | Wide spread; thin depth; halted market. |
| Evidence available | No event market data. |
| Missing implementation | Licensed quote data and a feasibility model. |
| Dependencies | MS3-30 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-14 — Causal Research

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 22 |
| Objective | Model an economic shock to a company financial outcome with an explicit estimand. |
| Input dataset | Economic panel plus issuer outcomes. |
| Legal data entitlement | public_domain. |
| Independent baseline | Pre-specified regression with controls. |
| Required outputs | Estimand, assumptions, labels, controls, sensitivity and null results. |
| Acceptance criteria | Explicit estimand and honest null reporting. |
| Existing tests | none |
| Adversarial cases | Confounded shock; weak instrument; regime break. |
| Evidence available | Only a design document exists. |
| Missing implementation | Estimation code and identification tests. |
| Dependencies | MS3-31 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-15 — Decision Robustness

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 22 |
| Objective | Solve a scenario-dependent research or investment choice. |
| Input dataset | Scenario set with explicit losses. |
| Legal data entitlement | project_authored. |
| Independent baseline | Do-nothing baseline and analytic cases. |
| Required outputs | Recommendation, payoffs, costs, uncertainty and reversal conditions. |
| Acceptance criteria | Show reversal or abstention under adverse assumptions. |
| Existing tests | none |
| Adversarial cases | Adversarial scenario; cost model error. |
| Evidence available | No decision framework. |
| Missing implementation | Decision-loss specification and robustness search. |
| Dependencies | MS3-31 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-16 — Domain-Pack Portability

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P3 |
| Specification | v3.0.0, Section 22 |
| Objective | Install a non-equity pack and create a research application with it. |
| Input dataset | A committed domain pack. |
| Legal data entitlement | project_authored. |
| Independent baseline | The same application on the core without the pack. |
| Required outputs | Installed pack, application and rights declaration. |
| Acceptance criteria | Uses the original objects, compiler, time capsule and SDK; no core schema fork. |
| Existing tests | `tests/test_phase8_applications.py` |
| Adversarial cases | Pack requiring a new core column; pack with restricted data. |
| Evidence available | A domain pack installs and executes on the unchanged substrate. |
| Missing implementation | A non-equity pack and a second pack kind. |
| Dependencies | MS3-18, MS3-32 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-17 — Evidence Conflict and Monitoring

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P2 |
| Specification | v3.0.0, Section 22 |
| Objective | Inject contradictory reports and revised settlement records. |
| Input dataset | Revisioned evidence fixtures. |
| Legal data entitlement | public_domain. |
| Independent baseline | Manual dependency tracing. |
| Required outputs | Conflict markers, preserved versions, invalidated dependents and explained consequences. |
| Acceptance criteria | Invalidate only dependent results. |
| Existing tests | `tests/test_evidence.py` |
| Adversarial cases | Contradictory amendments; deleted fact; stale cache. |
| Evidence available | Supersession and revision chains are stored and tested; dependency invalidation is partial. |
| Missing implementation | Dependency-aware invalidation and monitoring alerts. |
| Dependencies | MS3-7, MS3-17, MS3-52 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-18 — Value-of-Information Audit

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P4 |
| Specification | v3.0.0, Section 22 |
| Objective | Decide whether to buy data or run another experiment. |
| Input dataset | Candidate data offers and experiment costs. |
| Legal data entitlement | project_authored. |
| Independent baseline | Known analytical VOI cases. |
| Required outputs | VOI estimate under stated losses and compare with doing nothing. |
| Acceptance criteria | Reproduce VOI and the do-nothing baseline. |
| Existing tests | none |
| Adversarial cases | Mis-specified loss; correlated experiments. |
| Evidence available | No VOI implementation. |
| Missing implementation | Decision-loss model and VOI estimator. |
| Dependencies | MS3-53 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-19 — Real Estate Underwriting

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P4 |
| Specification | v3.0.0, Section 22 |
| Objective | Take an evidence-backed rental property to cash flows, debt, sale and investor return. |
| Input dataset | Lease and rent-roll evidence. |
| Legal data entitlement | user-authorised private data. |
| Independent baseline | Independent spreadsheet reconciliation. |
| Required outputs | NOI, capex, DSCR, equity cash flow, IRR and assumptions. |
| Acceptance criteria | Reconcile every line; separate facts from assumptions. |
| Existing tests | none |
| Adversarial cases | Vacancy spike; concession; refinancing; insurance shock. |
| Evidence available | Specification only. |
| Missing implementation | Property, lease and debt model. |
| Dependencies | MS3-33 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-20 — Property Risk and Spatial Evidence

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P4 |
| Specification | v3.0.0, Section 22 |
| Objective | Underwrite an asset under hazard, financing and insurance scenarios. |
| Input dataset | Spatial hazard data with release timestamps. |
| Legal data entitlement | public_domain or licensed. |
| Independent baseline | Independent geographic join. |
| Required outputs | Geographic joins, risk attribution, uncertainty and scenario results. |
| Acceptance criteria | Reproduce joins; prohibit false parcel-level claims. |
| Existing tests | none |
| Adversarial cases | Missing parcel; stale flood map; boundary change. |
| Evidence available | None. |
| Missing implementation | Spatial data fabric and risk attribution. |
| Dependencies | MS3-33 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-21 — Universal Model Catalog

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P2 |
| Specification | v3.0.0, Section 48 |
| Objective | Discover, import and execute built-in and custom models with distinct kinds. |
| Input dataset | Model registry entries and reference cases. |
| Legal data entitlement | project_authored. |
| Independent baseline | Reference mathematics per model. |
| Required outputs | Model metadata, coverage, status and outputs. |
| Acceptance criteria | Correct math and no false availability claims. |
| Existing tests | `tests/test_phase9_1_models.py` |
| Adversarial cases | Unsupported model kind; declared coverage gap. |
| Evidence available | Registry with declared coverage and audited DCF/bank models. |
| Missing implementation | Catalog breadth and coverage reporting. |
| Dependencies | MS3-36 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-22 — Graph Composition

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P2 |
| Specification | v3.0.0, Section 48 |
| Objective | Build the same nested model through visual, equation and SDK paths. |
| Input dataset | Nested model fixture. |
| Legal data entitlement | project_authored. |
| Independent baseline | Equation-path output. |
| Required outputs | Equivalent outputs, lineage and export. |
| Acceptance criteria | Equivalent results and reproducible export. |
| Existing tests | `tests/test_fec.py` |
| Adversarial cases | Type mismatch; cyclic graph; unsupported operator. |
| Evidence available | Equation/SDK composition with typed refusal is tested. |
| Missing implementation | Visual path. |
| Dependencies | MS3-37 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-23 — Model Tournament

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 48 |
| Objective | Compare baselines, ensembles and failures on as-of data. |
| Input dataset | As-of datasets and trial budget. |
| Legal data entitlement | project_authored. |
| Independent baseline | Fixed baseline set. |
| Required outputs | Complete trial log, calibrated metrics and bounded search. |
| Acceptance criteria | No invalid promotion; full trial accounting. |
| Existing tests | none |
| Adversarial cases | Selection leakage; multiple testing. |
| Evidence available | No tournament runner. |
| Missing implementation | Tournament protocol and multiple-testing correction. |
| Dependencies | MS3-37 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-24 — Global Terminal

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P1 |
| Specification | v3.0.0, Section 48 |
| Objective | Search, chart, screen and compare multiple instruments and event data. |
| Input dataset | Canonical market series with two providers and revisions. |
| Legal data entitlement | synthetic + restricted vendor. |
| Independent baseline | Per-security canonical selection executed independently. |
| Required outputs | Overview, chart, provenance, rights status and absent-feed disclosure. |
| Acceptance criteria | Correct instrument, time and source status; explicit feed limits. |
| Existing tests | `tests/test_phase9_2_8_bulk_overview.py`, `tests/test_phase9_2_7_market_series.py`, `tests/test_terminal_api.py` |
| Adversarial cases | Provider conflict; revision; holiday; stale security; restricted rights. |
| Evidence available | Canonical series, provenance, rights labels and bulk projection parity proven on synthetic data. |
| Missing implementation | Multi-asset coverage, live feeds and desktop/mobile acceptance at this revision. |
| Dependencies | MS3-38 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-25 — Quant Stack Reproduction

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 48 |
| Objective | Recreate accepted nightly, ETF, options and paper templates. |
| Input dataset | The user's existing templates. |
| Legal data entitlement | user-supplied. |
| Independent baseline | Original tool outputs. |
| Required outputs | Reproduced models, performance status and isolation. |
| Acceptance criteria | Source-compatible fixtures and honest performance status. |
| Existing tests | none |
| Adversarial cases | Missing dependency; broker isolation breach. |
| Evidence available | No importer exists. |
| Missing implementation | Template importer and parity harness. |
| Dependencies | MS3-46 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-26 — Banking Model

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 48 |
| Objective | M&A and LBO case with spreadsheet export. |
| Input dataset | Deal assumptions and filings. |
| Legal data entitlement | project_authored. |
| Independent baseline | Independent banking reconciliation. |
| Required outputs | Sources/uses, debt, earnings, dilution and returns. |
| Acceptance criteria | Independent reconciliation of every schedule. |
| Existing tests | none |
| Adversarial cases | Circular interest; negative equity; revolver draw. |
| Evidence available | Only bank valuation exists, not M&A/LBO. |
| Missing implementation | Transaction model and export. |
| Dependencies | MS3-42 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-27 — Private Markets

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P4 |
| Specification | v3.0.0, Section 48 |
| Objective | Multi-round capitalization and GP/LP fund case. |
| Input dataset | Cap table and fund terms. |
| Legal data entitlement | user-authorised private. |
| Independent baseline | Reference cap-table examples. |
| Required outputs | Waterfall, distributions and fund metrics. |
| Acceptance criteria | Reproduce reference outcomes. |
| Existing tests | none |
| Adversarial cases | Liquidation preference conflict; anti-dilution; carry hurdle. |
| Evidence available | None. |
| Missing implementation | Private-market model. |
| Dependencies | MS3-43 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-28 — Household Planning

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 48 |
| Objective | Accounts or imports, debt and retirement scenarios. |
| Input dataset | User accounts and imported statements. |
| Legal data entitlement | user-authorised private. |
| Independent baseline | Independent planner reference. |
| Required outputs | Consent record, reconciled balances, scenarios and uncertainty. |
| Acceptance criteria | Privacy, reconciliation and novice comprehension. |
| Existing tests | none |
| Adversarial cases | Missing statement month; currency mismatch. |
| Evidence available | None. |
| Missing implementation | Accounts, consent and planning model. |
| Dependencies | MS3-44 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-29 — Portfolio Operations

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P2 |
| Specification | v3.0.0, Section 48 |
| Objective | Multi-asset holdings, targets, P&L, corporate actions and factor risk. |
| Input dataset | Broker records and prices. |
| Legal data entitlement | user-authorised. |
| Independent baseline | Independent portfolio accounting. |
| Required outputs | Positions, cash, P&L, risk and scenario report. |
| Acceptance criteria | No double allocation; correct cash, fees and actions. |
| Existing tests | none |
| Adversarial cases | Split on holding date; fee accrual; FX revaluation. |
| Evidence available | None. |
| Missing implementation | Portfolio ledger and risk. |
| Dependencies | MS3-41 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-30 — UX Role Continuity

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 48 |
| Objective | Novice and professional complete comparable workflows. |
| Input dataset | Usability protocol with two cohorts. |
| Legal data entitlement | project_authored. |
| Independent baseline | Task-completion and comprehension measures. |
| Required outputs | Session records, task outcomes and accessibility findings. |
| Acceptance criteria | Same mathematics with progressive controls. |
| Existing tests | none |
| Adversarial cases | Misleading label; mobile viewport; keyboard-only path. |
| Evidence available | No usability study has been run. |
| Missing implementation | Usability protocol and accessibility audit. |
| Dependencies | MS3-45 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-31 — Plugin and Rights

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P2 |
| Specification | v3.0.0, Section 48 |
| Objective | Third-party model or application uses licensed and private datasets. |
| Input dataset | A third-party package with restricted inputs. |
| Legal data entitlement | mixed. |
| Independent baseline | Manual permission inspection. |
| Required outputs | Permission decisions, sandbox result, export and attribution. |
| Acceptance criteria | Permission, sandbox and untrusted-code checks. |
| Existing tests | `tests/test_phase8_applications.py` |
| Adversarial cases | Malicious package; symlink escape; restricted export. |
| Evidence available | Package rights and zip-safety are tested; no sandbox for untrusted Python. |
| Missing implementation | Process isolation for third-party code. |
| Dependencies | MS3-9, MS3-18 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-32 — Operational Reliability

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P2 |
| Specification | v3.0.0, Section 48 |
| Objective | Fail, retry, cancel, stale-feed and recover on realistic workloads. |
| Input dataset | Fault-injection harness. |
| Legal data entitlement | project_authored. |
| Independent baseline | Baseline single-node run. |
| Required outputs | State after failure, resource bounds, freshness and alerts. |
| Acceptance criteria | Correct state and bounded resources. |
| Existing tests | `tests/test_release_security_9_2_5.py`, `tests/test_sec_transport_limits.py` |
| Adversarial cases | Truncated response; oversized body; interrupted ingest. |
| Evidence available | Transport bounds and compressed-response safety are tested offline. |
| Missing implementation | Retry, cancellation, stale-feed detection and alerts. |
| Dependencies | MS3-20 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-33 — Evidence Version Fidelity

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P1 |
| Specification | v3.0.0, Section 60 |
| Objective | Original versus amended filings and macro vintages are selected correctly. |
| Input dataset | Restatement fixtures with acceptance timestamps. |
| Legal data entitlement | public_domain. |
| Independent baseline | Differential SQL selection. |
| Required outputs | As-of facts, excluded facts and precision. |
| Acceptance criteria | False time-travel results rejected. |
| Existing tests | `tests/test_history.py` |
| Adversarial cases | Same-day amendment; missing acceptance time. |
| Evidence available | Filing-level as-of selection is tested differentially. |
| Missing implementation | Macro vintages. |
| Dependencies | MS3-7, MS3-17 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-34 — Financial RAG Grounding

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P2 |
| Specification | v3.0.0, Section 60 |
| Objective | Correct source-span support, numerical answers, abstention and conflict handling on independent QA cases. |
| Input dataset | Independent financial QA set with gold spans. |
| Legal data entitlement | public_domain. |
| Independent baseline | Lexical BM25 and hybrid baselines. |
| Required outputs | Answers with spans, numbers, abstentions and conflicts. |
| Acceptance criteria | Grounded accuracy, abstention and conflict metrics. |
| Existing tests | none |
| Adversarial cases | Unanswerable question; contradictory filings; table question. |
| Evidence available | No retrieval layer exists. |
| Missing implementation | FKE and an evaluation harness. |
| Dependencies | MS3-49, MS3-57 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-35 — Compression Reconstruction

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 60 |
| Objective | Byte-exact original recovery with hashes, the version graph and recovery after corruption. |
| Input dataset | Versioned document corpus with hashes. |
| Legal data entitlement | public_domain. |
| Independent baseline | Uncompressed baseline. |
| Required outputs | Reconstructed bytes, hashes and recovery report. |
| Acceptance criteria | Byte-exact reconstruction and safe corruption handling. |
| Existing tests | none |
| Adversarial cases | Truncated stream; corrupted block; adversarial input. |
| Evidence available | Research hypothesis only. |
| Missing implementation | Encoder, decoder and corruption tests. |
| Dependencies | MS3-50 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-36 — Compressed Search Frontier

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 60 |
| Objective | Total bytes, p95 latency and correct-version recall against strong lexical/hybrid baselines. |
| Input dataset | The same corpus with fixed availability times. |
| Legal data entitlement | public_domain. |
| Independent baseline | BM25, hybrid and vector baselines. |
| Required outputs | Byte accounting, latency and recall. |
| Acceptance criteria | Quality-matched or better at lower total cost. |
| Existing tests | none |
| Adversarial cases | Rare token; revised document; long document. |
| Evidence available | No compression or retrieval system. |
| Missing implementation | Encoder plus baseline harness. |
| Dependencies | MS3-50, MS3-57 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-37 — Evidence-Salient Changes

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 60 |
| Objective | Detect rare numbers, negations, footnotes, deleted/revised facts and falsifying evidence. |
| Input dataset | Annotated revision pairs. |
| Legal data entitlement | public_domain. |
| Independent baseline | Manual annotation. |
| Required outputs | Salience marks and grounded explanation. |
| Acceptance criteria | No ungrounded summaries; recall on rare changes. |
| Existing tests | none |
| Adversarial cases | Subtle negation; footnote-only change. |
| Evidence available | None. |
| Missing implementation | Diff and salience pipeline. |
| Dependencies | MS3-49, MS3-50 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-38 — Adaptive Research Plan

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P2 |
| Specification | v3.0.0, Section 60 |
| Objective | Typed plans for retail, quant, banking and research tasks. |
| Input dataset | Task suite across four roles. |
| Legal data entitlement | project_authored. |
| Independent baseline | Expert-authored reference plans. |
| Required outputs | Typed, permission-aware, editable plan. |
| Acceptance criteria | Bad sources, permissions and action types rejected. |
| Existing tests | none |
| Adversarial cases | Ambiguous goal; disallowed source; over-broad plan. |
| Evidence available | No planner exists. |
| Missing implementation | Plan schema and IRC. |
| Dependencies | MS3-51 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-39 — Research Integrity

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P1 |
| Specification | v3.0.0, Section 60 |
| Objective | Independently pass/fail evidence, computational, statistical and decision checks. |
| Input dataset | Cases with known defects. |
| Legal data entitlement | project_authored. |
| Independent baseline | Independent reviewer. |
| Required outputs | Findings per check with blockers. |
| Acceptance criteria | Correct pass/fail and explained blockers. |
| Existing tests | `tests/test_phase9_1_models.py`, `scripts/audit_phase9_2_models.py` |
| Adversarial cases | Arithmetic-only correctness claimed as full validity; contamination. |
| Evidence available | Model Auditor and independent audits produce per-check findings. |
| Missing implementation | Statistical-validity and decision checks. |
| Dependencies | MS3-52 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-40 — Resource Optimization

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 60 |
| Objective | Show measured quality-matched reduction in cost, time or peak resources versus fixed policies. |
| Input dataset | Changing workloads with fixed correctness targets. |
| Legal data entitlement | project_authored. |
| Independent baseline | Fixed policy baselines. |
| Required outputs | Cost, time, peak memory and quality. |
| Acceptance criteria | Measured improvement under changed workloads. |
| Existing tests | `scripts/benchmark_market_overview.py` |
| Adversarial cases | Workload shift; cache cold start. |
| Evidence available | One projection plan is benchmarked; no policy engine. |
| Missing implementation | Policy selection engine. |
| Dependencies | MS3-53 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-41 — Data Coverage Transparency

| Field | Value |
| --- | --- |
| Status | `prototype_verified` |
| Priority | P2 |
| Specification | v3.0.0, Section 60 |
| Objective | Correct freshness, quality, rights, historical universe and conflict indicators. |
| Input dataset | Datasets with known gaps and conflicts. |
| Legal data entitlement | mixed. |
| Independent baseline | Manual coverage audit. |
| Required outputs | Coverage, freshness, rights and conflict fields. |
| Acceptance criteria | No synthetic/live confusion. |
| Existing tests | `tests/test_phase9_2_2_market_observations.py` |
| Adversarial cases | Synthetic feed labelled reported; stale session; restricted source. |
| Evidence available | Source status, synthetic labelling and missing-session counts are surfaced and differentially tested. |
| Missing implementation | Unified coverage dashboard; historical universe. |
| Dependencies | MS3-54 |
| Executed | not recorded |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-42 — Pipeline Failure Recovery

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P2 |
| Specification | v3.0.0, Section 60 |
| Objective | Detect stale table reads, missing bars, schema drift, bad calendars, retry/cancel and deterministic replay. |
| Input dataset | Fault injection across the pipeline. |
| Legal data entitlement | project_authored. |
| Independent baseline | Healthy baseline run. |
| Required outputs | Detected faults, recovery state and replay equality. |
| Acceptance criteria | Deterministic replay after recovery. |
| Existing tests | none |
| Adversarial cases | Corrupt database; calendar hole; partial write. |
| Evidence available | Only transport-level bounds are tested. |
| Missing implementation | Pipeline fault detection and replay. |
| Dependencies | MS3-32 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-43 — Cross-View Model Parity

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 60 |
| Objective | Visual, formula, tabular and SDK representations match or declare exact differences. |
| Input dataset | A model with multiple representations. |
| Legal data entitlement | project_authored. |
| Independent baseline | Formula-path output. |
| Required outputs | Four representations and a parity report. |
| Acceptance criteria | Match or explicit declared differences. |
| Existing tests | `tests/test_fec.py` |
| Adversarial cases | Unsupported construct; rounding policy. |
| Evidence available | Only the equation/SDK paths exist. |
| Missing implementation | Visual and table views. |
| Dependencies | MS3-55 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-44 — Professional Artifact Migration

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 60 |
| Objective | Import a working spreadsheet or notebook and reconcile outputs without hiding unsupported formulas. |
| Input dataset | User-supplied workbook and notebook. |
| Legal data entitlement | user-authorised. |
| Independent baseline | The original workbook's own outputs. |
| Required outputs | Imported model, reconciliation table and unsupported list. |
| Acceptance criteria | Reconciled outputs and explicit unsupported constructs. |
| Existing tests | none |
| Adversarial cases | Volatile function; external link; circular reference. |
| Evidence available | None. |
| Missing implementation | Spreadsheet/notebook importer. |
| Dependencies | MS3-56 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-45 — Novice-to-Professional UX

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 60 |
| Objective | Role-spanning completion of the same task with equivalent mathematics and meaningful accessibility. |
| Input dataset | Two cohorts, one task. |
| Legal data entitlement | project_authored. |
| Independent baseline | Same model executed by both paths. |
| Required outputs | Session records, equality of mathematics, accessibility findings. |
| Acceptance criteria | Equivalent math and measurable accessibility. |
| Existing tests | none |
| Adversarial cases | Mobile viewport; keyboard-only; screen reader. |
| Evidence available | No accessibility audit has been run. |
| Missing implementation | Protocol and audit. |
| Dependencies | MS3-45 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-46 — Private Data Isolation

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P2 |
| Specification | v3.0.0, Section 60 |
| Objective | Household, deal and team records cannot leak into published apps, agents or reports. |
| Input dataset | Private fixtures plus a published artefact. |
| Legal data entitlement | user-authorised private. |
| Independent baseline | Manual inspection of every export. |
| Required outputs | Isolation report and blocked paths. |
| Acceptance criteria | No leakage across boundaries. |
| Existing tests | none |
| Adversarial cases | Nested package; cached query; report embedding. |
| Evidence available | No private-data tenancy exists. |
| Missing implementation | Isolation model and tests. |
| Dependencies | MS3-20, MS3-56 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-47 — Scientific Generalization

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P3 |
| Specification | v3.0.0, Section 60 |
| Objective | Retrieval and compression advantages replicate across independent finance and non-finance corpora. |
| Input dataset | Independent corpora plus adversarial cases. |
| Legal data entitlement | public_domain. |
| Independent baseline | Published baselines. |
| Required outputs | Replication results including failures. |
| Acceptance criteria | Pre-registered replication with negative results reported. |
| Existing tests | none |
| Adversarial cases | Domain shift; adversarial paraphrase. |
| Evidence available | No study exists. |
| Missing implementation | Protocol and independent corpora. |
| Dependencies | MS3-57 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |

### ICB-48 — End-to-End Research Substitution

| Field | Value |
| --- | --- |
| Status | `vision_only` |
| Priority | P0 |
| Specification | v3.0.0, Section 60 |
| Objective | Complete one real equity-research task from original filings to a verified memo and monitoring. |
| Input dataset | Real SEC filings for one issuer plus a licensed price feed. |
| Legal data entitlement | public_domain + licensed. |
| Independent baseline | An analyst memo produced independently. |
| Required outputs | Memo, evidence links, model, scenarios and monitoring record. |
| Acceptance criteria | Declared tool and data dependencies; verified memo. |
| Existing tests | `tests/test_phase9_equity.py`, `tests/test_phase9_3_research_memo.py` |
| Adversarial cases | Restatement mid-task; missing price date; conflicting sources. |
| Evidence available | Phase 9.3 supplies memo authoring, claim verification, exports and deterministic change detection; the benchmark is not accepted. |
| Missing implementation | An independently produced analyst baseline, licensed price feed, narrative retrieval and notification delivery. |
| Dependencies | MS3-59, MS3-49 |
| Executed | no |
| Recorded | 2026-11-10 at `cf67cdf6a1bcc2f29b29dc71967d84263eaa6590` |
