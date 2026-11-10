# ATLAS QUANT
## Master Product, Architecture, Research, and Execution Specification

**Version:** 3.0.0  
**Date:** 2026-11-09  
**Status:** Canonical desired-state specification; implementation claims require independent verification  
**Document path:** `ATLAS_MASTER_SPEC.md` (distribution copy: `ATLAS_MASTER_SPEC_V3_FINAL.md`)  
**Product class:** Open-source universal financial research, modeling, market intelligence, decision and application operating system  
**Design principle:** One verified financial substrate with progressive interface depth, universal model composition, professional end-to-end workflows and consumer accessibility

> **North star:** Make serious financial research, modeling, strategy science, portfolio analysis, transaction work and personal planning possible in one open, trusted environment. Research anything financially computable, invent and combine compatible models, inspect the evidence, test honestly, preserve uncertainty and turn work into reusable applications.

**What this document is:** The consolidated desired-state master specification for Atlas Quant. It preserves the original eight-system architecture, temporal evidence and compiler contracts, expanded events/decision and real-estate packs, and the historical Phase 1 through Phase 3 agent-reported baseline. Version 2 added a universal professional-and-consumer financial operating system charter, role-based end-to-end workflows, the named financial model library, guaranteed typed model composition, trading and institutional operations, investment banking, private capital, personal finance, Quant Stack compatibility requirements, extended benchmarks, and adoption gates. Data, product and competitive claims require evidence; this document is a specification rather than evidence that the code exists.

**Version 3 scope rule:** The additions in Sections 49-60 are cross-cutting capability contracts implemented through the original eight systems. They do not require new permanent navigation tabs or a second system of evidence, financial computation or permissions. All compression and AI research results must be distinguished from verified production capabilities and independently replicated scientific findings.

**What this document is not:** A claim that the current code already implements everything below, a guarantee that Atlas will outperform a proprietary terminal, permission to redistribute commercial data, or an instruction to integrate every listed open-source project. This document deliberately distinguishes requirements, hypotheses, implementation reports, and proven performance.

**Document precedence:** (1) laws, licenses, safety, source terms, and security obligations; (2) approved versioned contracts and ADRs for deployed components; (3) this master specification for product direction; (4) phase plans; (5) informal feature ideas. If a deployed contract conflicts with this vision, propose and verify a migration rather than silently breaking it. Amend this document through a reviewed change with an explicit rationale.

**v3.0 change note (2026-11-09):** Retained the original eight-system platform and the complete v2.0 professional-and-consumer specification, including the 32 earlier ICB suites. Added a Financial Knowledge Engine; formal evidence-preserving compression/CDG research contracts; Intent-to-Research Compiler; Research Integrity Engine; Industrial Engineering Resource Optimization Engine; Data Coverage and Integrity Center; synchronized multi-view Model Experience System; professional migration and deliverable portability; scientific RAG/AI/operations-research experiments; a candidate repository adoption registry; staged product-and-adoption gates; and ICB-33 through ICB-48. Reorganized final charter as Section 61. New features are proposed requirements and hypotheses unless their implementation and evidence are independently verified.

**v2.0 change note (2026-11-08):** Expanded Atlas from a financial-first research environment into the proposed universal financial operating system, while preserving the eight-system platform. Added Sections 34 through 48 and the original final charter (now retained as Section 61). Explicitly mapped the user-supplied investing model taxonomy, the four tools and sixteen reported gaps from *Quant Stack: Capabilities and Gaps* (November 8, 2026), institutional and consumer workflows, Model Forge composition, specialist and beginner UX, broker/account safety, professional deliverables, and ICB-21 through ICB-32. These are new requirements, not claims of implementation, backtested profitability or institutional parity.

**v1.2 change note:** Promoted Real Assets & Infrastructure into an explicit **Atlas Real Estate Investment Intelligence** domain pack without changing the eight-system platform. Added the real-property ontology, lease/debt/asset-level cash-flow modeling, REIT/CMBS boundaries, spatial-temporal evidence, lawful public data sources, ICB-19/20, and phased delivery gates. Property-level precision, comparables, transactions and insurance must be evidence-backed or modeled as uncertain assumptions. This is a strategic specification update, not an implementation claim.

**v1.1 change note:** Incorporated the user-supplied Universal Intelligence / Event Market expansion after critique. Added Sections 29–32, ICB-11 through ICB-18, schema extensions throughout existing layers, external data-rights/market rules, and agent-reported Phase 3 checkpoint. Financial research remains the primary product; event markets and other domains are opt-in research packages. This is a specification revision, not a code deployment.

## Contents

- [1. Mission, positioning, and the standard of success](#1-mission-positioning-and-the-standard-of-success)
- [2. Product model: Eight integrated systems, one experience](#2-product-model-eight-integrated-systems-one-experience)
- [3. Interface: almost limitless depth with minimal visible clutter](#3-interface-almost-limitless-depth-with-minimal-visible-clutter)
- [4. Replaceability and competition](#4-replaceability-and-competition)
- [5. Architecture: the unified financial computing substrate](#5-architecture-the-unified-financial-computing-substrate)
- [6. Universal Research Object System (UROS)](#6-universal-research-object-system-uros)
- [7. Data Fabric, Temporal Evidence Kernel, and source quality](#7-data-fabric-temporal-evidence-kernel-and-source-quality)
- [8. Financial-Economic Ontology and entity graph](#8-financial-economic-ontology-and-entity-graph)
- [9. Data Rights Engine and sustainable open-source economics](#9-data-rights-engine-and-sustainable-open-source-economics)
- [10. Financial-Economic Compiler: the central original engineering asset](#10-financial-economic-compiler-the-central-original-engineering-asset)
- [11. Universal Execution Runtime and storage/compute architecture](#11-universal-execution-runtime-and-storagecompute-architecture)
- [12. Model Forge: unrestricted model creativity with enforced contracts](#12-model-forge-unrestricted-model-creativity-with-enforced-contracts)
- [13. Quant Lab, Alpha Foundry, and historical strategy simulation](#13-quant-lab-alpha-foundry-and-historical-strategy-simulation)
- [14. Institutional valuation, fixed income, derivatives, and portfolio risk](#14-institutional-valuation-fixed-income-derivatives-and-portfolio-risk)
- [15. Atlas Intelligence: a real brain, not a mandatory chatbot](#15-atlas-intelligence-a-real-brain-not-a-mandatory-chatbot)
- [16. Global OSINT, news intelligence, and the Economic Reality Engine](#16-global-osint-news-intelligence-and-the-economic-reality-engine)
- [17. Research Operating System, Time Capsule, and Sentinel](#17-research-operating-system-time-capsule-and-sentinel)
- [18. Financial Application Compiler and plugin ecosystem](#18-financial-application-compiler-and-plugin-ecosystem)
- [19. API, SDK, scripting, and extension contracts](#19-api-sdk-scripting-and-extension-contracts)
- [20. Security, privacy, safety, and operational governance](#20-security-privacy-safety-and-operational-governance)
- [21. Stack evolution and implementation discipline](#21-stack-evolution-and-implementation-discipline)
- [22. Institutional Capability Benchmark (ICB)](#22-institutional-capability-benchmark-icb)
- [23. Development roadmap, priorities, and release gates](#23-development-roadmap-priorities-and-release-gates)
- [24. Architecture decision record and contribution governance](#24-architecture-decision-record-and-contribution-governance)
- [25. Strategic risks and mitigation](#25-strategic-risks-and-mitigation)
- [26. Canonical end-to-end research demonstrations](#26-canonical-end-to-end-research-demonstrations)
- [27. Research source and software inventory](#27-research-source-and-software-inventory)
- [28. Instructions for all future Atlas engineering agents](#28-instructions-for-all-future-atlas-engineering-agents)
- [29. Expansion decision and domain boundaries](#29-expansion-decision-and-domain-boundaries)
- [30. Universal Event and Probability Engine](#30-universal-event-and-probability-engine)
- [31. Causal, decision, and opportunity intelligence](#31-causal-decision-and-opportunity-intelligence)
- [32. Domain packs, implementation gates, and event benchmarks](#32-domain-packs-implementation-gates-and-event-benchmarks)
- [33. Atlas Real Estate Investment Intelligence](#33-atlas-real-estate-investment-intelligence)
- [34. Platform constitution: the universal financial operating system](#34-platform-constitution-the-universal-financial-operating-system)
- [35. Users, complete jobs and adoption-critical workflows](#35-users-complete-jobs-and-adoption-critical-workflows)
- [36. Universal investment model library and coverage contracts](#36-universal-investment-model-library-and-coverage-contracts)
- [37. Model composition, invention and computational research](#37-model-composition-invention-and-computational-research)
- [38. Global financial terminal and market intelligence](#38-global-financial-terminal-and-market-intelligence)
- [39. Equity, fundamental, accounting and research desk](#39-equity-fundamental-accounting-and-research-desk)
- [40. Quantitative trading, strategy science and execution research](#40-quantitative-trading-strategy-science-and-execution-research)
- [41. Institutional portfolio management, risk and operations](#41-institutional-portfolio-management-risk-and-operations)
- [42. Investment banking and transaction intelligence](#42-investment-banking-and-transaction-intelligence)
- [43. Venture capital, private equity, private credit and fund intelligence](#43-venture-capital-private-equity-private-credit-and-fund-intelligence)
- [44. Personal finance, wealth and consumer decision support](#44-personal-finance-wealth-and-consumer-decision-support)
- [45. Adaptive experience, human factors and professional workflow design](#45-adaptive-experience-human-factors-and-professional-workflow-design)
- [46. Quant Stack compatibility and migration contract](#46-quant-stack-compatibility-and-migration-contract)
- [47. Enterprise, institutions, connectivity and deliverable interoperability](#47-enterprise-institutions-connectivity-and-deliverable-interoperability)
- [48. Release strategy, external benchmarks and ecosystem growth](#48-release-strategy-external-benchmarks-and-ecosystem-growth)
- [49. Financial Knowledge Engine: unified, evidence-preserving retrieval](#49-financial-knowledge-engine-unified-evidence-preserving-retrieval)
- [50. Compression, CDG and evidence-preserving data research](#50-compression-cdg-and-evidence-preserving-data-research)
- [51. Intent-to-Research Compiler and adaptive workflows](#51-intent-to-research-compiler-and-adaptive-workflows)
- [52. Research Integrity Engine: evidence, mathematics and decisions](#52-research-integrity-engine-evidence-mathematics-and-decisions)
- [53. Atlas Resource Optimization Engine: the industrial engineering core](#53-atlas-resource-optimization-engine-the-industrial-engineering-core)
- [54. Data Coverage, Integrity and Service Health Center](#54-data-coverage-integrity-and-service-health-center)
- [55. Model Experience System and adaptive human-computer interaction](#55-model-experience-system-and-adaptive-human-computer-interaction)
- [56. Workflow Portability, Migration and Professional Deliverables](#56-workflow-portability-migration-and-professional-deliverables)
- [57. ResearchOS scientific program for AI, RAG, compression and IE](#57-researchos-scientific-program-for-ai-rag-compression-and-ie)
- [58. Open-source integration and dependency evaluation registry](#58-open-source-integration-and-dependency-evaluation-registry)
- [59. Product delivery sequence and cross-domain user adoption](#59-product-delivery-sequence-and-cross-domain-user-adoption)
- [60. New Institutional Capability Benchmarks and acceptance matrix](#60-new-institutional-capability-benchmarks-and-acceptance-matrix)
- [61. Final platform definition and strategic charter](#61-final-platform-definition-and-strategic-charter)

---

## 1. Mission, positioning, and the standard of success

### 1.1 The mission

Build the most capable **open, locally runnable, programmable financial research environment** practical, with a free core whose mathematics, research methods, code interfaces, and model construction are not artificially paywalled. A person should be able to progress from examining a chart to designing and validating an original multi-asset or economic research system **without leaving Atlas**.

Atlas aims to replace a large fraction of the daily research workflows for which users currently combine Bloomberg, TradingView, thinkorswim, Python notebooks, spreadsheet models, data portals, risk systems, and disparate AI tools. The goal is not to reproduce proprietary networks, guaranteed ultra-low-latency news, every exchange feed, or private contributor datasets without licensing.

**Competitive thesis:** Atlas wins on *integrated research capability, openness, customizability, mathematical rigor, historical integrity, reproducibility, and local economics*, not a theatrical count of dashboard panels. An institutional-grade computation system can be open even when particular underlying market datasets are licensed.

### 1.2 Define institutional-grade precisely

For Atlas, institutional-grade means demonstrable properties:

1. **Financial semantic correctness:** assets, instruments, accounting concepts, dates, currencies, units, conventions, and corporate actions are represented accurately.
2. **Point-in-time integrity:** backtests and historical studies cannot silently see later information. Gaps and ambiguous timestamps remain visible.
3. **Independent numerical validation:** core models are cross-checked against published methods, reference libraries, analytical cases, and stable test vectors.
4. **Reproducibility:** complete experiment manifests, code versions, datasets, model checkpoints, assumptions, random seeds, execution engines, and outputs are recorded.
5. **Practical scalability:** measurements on realistic numbers of securities, observations, factors, models, and portfolios are published with hardware details.
6. **Professional workflow depth:** financial statements, valuation, pricing, risk, portfolio analytics, simulation, and research findings are connected rather than isolated.
7. **Auditability:** users can inspect the evidence behind results and the calculation path between them.
8. **Security and governance:** user code, source permissions, sensitive information, and live trading permissions are isolated and controlled.

**Not required for institutional-grade research:** a Bloomberg-like visual theme, thousands of superficial widgets, automatic profits, or owning the fastest newswire.

### 1.3 Core product promise

Atlas is both a terminal and a **financial computing substrate**. A user may discover an observation, build a mathematical model from it, train a neural network, test a strategy, run a scenario, inspect and challenge the results, and publish the workflow as an interactive, versioned research application. One connected model underlies every view.

### 1.4 Users and jobs

| User | Core job | Atlas must provide |
|---|---|---|
| Curious investor | Understand a company, market, and risk | Straightforward research, charts, filings, and explanations |
| Fundamental analyst | Underwrite a business and alternatives | Three-statement modeling, valuation, filings, revisions, peer comparison |
| Quant researcher | Discover and test hypotheses | Point-in-time features, statistical methods, ML, backtesting, experiment audit |
| Portfolio/risk researcher | Optimize and explain exposures | Portfolio accounting, factor and scenario risk, constrained optimization |
| Credit/rates/derivatives analyst | Price and risk financial instruments | Curves, cash flows, models, sensitivities, validated conventions |
| Real estate investor or analyst | Underwrite properties, portfolios, developments, REITs and property debt | Lease-aware cash flows, debt waterfalls, property risk, spatial market evidence and scenario analysis |
| Economic/OSINT researcher | Map real-world signals to companies | Source-grounded entities, relationships, events, economic models |
| Developer/research engineer | Invent new tools and algorithms | SDK, typed DSL/IR, sandboxed extensions, reproducible apps |
| Research team | Share models and review conclusions | Versioning, permissions, reviews, lineage, deployment as optional add-ons |

### 1.5 Non-goals and permanent guardrails

- Do not claim equivalence to the Bloomberg data network or access to restricted sources that Atlas does not possess.
- Do not confuse a market-data *refresh interval* with guaranteed provider latency or authoritative exchange time.
- Do not present synthetic, inferred, stale, indicative, or model-estimated quantities as observed tradeable prices or verified facts.
- Do not train a giant proprietary LLM from scratch merely to call Atlas a financial AI company.
- Do not silently execute real-money orders. Trading, if added, is a separately permissioned subsystem with paper mode by default.
- Do not build complexity for its own sake, migrate from working code without evidence, or adopt dozens of heavyweight distributed components prematurely.
- Do not make access to core financial mathematics, supported modeling tools, backtesting, or local AI integration dependent on a mandatory subscription.
- Do not make autonomous AI required for deterministic core workflows.

---

## 2. Product model: Eight integrated systems, one experience

The original Atlas vision's eight systems remain authoritative. New developments deepen these systems, not replace them.

| # | System | Expanded charter |
|---|---|---|
| 1 | **Financial Terminal** | Multi-asset discovery, charting, screeners, linked workspaces, security research, news, portfolios, events, options and rates views where data exists |
| 2 | **Fundamental Research** | Company accounting, segment models, financial forensics, valuation, credit and property underwriting, market-implied expectations, earnings research |
| 3 | **Quantitative Research OS** | Factors, econometrics, neural networks, strategy development, backtesting, optimization, market microstructure, experimental science |
| 4 | **Global OSINT Intelligence** | Public records, physical infrastructure, trade, geographic data, government procurement, satellite, energy, transportation, technology, geopolitical events |
| 5 | **Economic Simulation** | Operating-model scenarios, real estate and infrastructure shocks, economic networks, structural shocks, industry digital twins, Monte Carlo, counterfactual and macro models |
| 6 | **Financial-Economic Compiler** | Typed, versioned financial IR, validation, optimization, heterogeneous execution, dependency tracking, reactive recomputation |
| 7 | **Research Operating System** | Financial X-Ray, Time Machine, thesis versioning, reproducible experiments, adversarial model audit, Research Sentinel |
| 8 | **Dynamic Workspace System** | Adaptive canvases, Standard and Advanced modes, visual/code/model composition, research applications, extensibility and optional AI creation |

**Cross-cutting platform capabilities:** Atlas Intelligence, Universal Research Objects, Universal Event and Probability Engine, Data Rights Engine, Financial-Economic Ontology, Model Forge, Alpha Foundry, Data Fabric, heterogeneous compute, permissions, and app/extension SDKs. These are underlying shared services, not additional permanently visible top-level products.

### 2.1 The five flagship outcomes

1. **Financial X-Ray:** click any output and traverse to source observations, calculation graph, versions, transforms, assumptions, time semantics, and confidence.
2. **Financial Time Machine:** reconstruct historical knowledge, not just historical candles; replay evidence, versions, and research decisions with explicit missing-information limits.
3. **Reality-to-Market Reconciliation:** infer assumptions consistent with prices or spreads, then compare them against operational constraints and grounded evidence; do not claim a unique explanation when underdetermined.
4. **Alpha Foundry:** invent and compare statistical, symbolic, neural, and strategy models under controlled point-in-time evaluation and realistic transaction costs.
5. **Economic Reality Simulator:** propagate explicitly stated real-world economic scenarios through supported entity relationships, operating models, statements, prices, risk, and portfolios, with uncertainty tracked throughout.

### 2.2 The one-sentence user experience

**Open a financial object or evidence-backed event, investigate it, build a model, test a forecast or decision, and keep the research alive as evidence changes.**

### 2.3 Version 2 universal financial-workflow coverage

The existing eight systems remain the infrastructure classification. They serve twelve contextual capability families without creating twelve top-level products: (1) Global Financial Terminal, (2) Fundamental and Equity Research, (3) Quantitative Research and AI, (4) Trading and Microstructure, (5) Institutional Asset Management and Risk, (6) Investment Banking and Corporate Finance, (7) Venture Capital/Private Equity/Private Credit, (8) Real Estate and Infrastructure, (9) Personal Finance and Wealth, (10) Global Economic Intelligence, (11) Event and Decision Intelligence, and (12) Financial Applications and Collaboration. The detailed v2 role and implementation contracts are Sections 34-48; v3 cross-cutting additions are Sections 49-60. Every workflow reuses UROS, FEC, Data Fabric, the Temporal Evidence Kernel and rights/permission checks.


---

## 3. Interface: almost limitless depth with minimal visible clutter

The principal navigation has only **Explore, Studio, Lab, Monitor**.

- **Explore:** companies, securities, markets, financial statements, charts, macro, OSINT, filings, historical evidence, prices, portfolio views.
- **Studio:** equations, model creation, custom indicators, neural architectures, data pipelines, tools, simulations, strategy specifications, portable financial research applications.
- **Lab:** training, inference evaluations, backtests, numerical solvers, sensitivity and scenario studies, model comparisons, research audits, scientific experiments.
- **Monitor:** watchlists, portfolios, theses, datasets, model validity, source changes, dependency invalidation, scheduled approved research, alerts.

A global command bar provides deterministic search, expert keyboard commands, context actions, and optional AI prompts. Advanced and Standard are **progressive disclosure modes over the same financial engine**. They may differ in layout and visible control complexity, never in numerical truth.

### 3.1 Adaptive canvas rules

- The default workspace emphasizes one primary research canvas; navigation and inspector are collapsible.
- Context determines available actions: *Explain, Model, Test, Compare, Simulate, Monitor, Export, Share* where meaningful.
- Every visual panel consumes typed read models and exposes provenance/freshness/limitations when applicable.
- Rich linked windows, chart drawing tools, hotkeys, command aliases, saved layouts, watchlists, and screeners are available as capabilities, not unavoidable chrome.
- All controls must have real behavior; no fake 'live' tickers, filler signals, or mislabeled synthetic data.
- Dynamic workspace schemas can be manually edited, visually composed, or generated by AI, with identical validation and permission checks.
- Accessibility, responsive layouts, keyboard focus, user preferences, and low-motion modes are core product requirements.
- Code output, debug logs, optimizer traces, and extensive settings appear on demand, not as default permanent panels.

### 3.2 Expert speed without intimidation

Use Bloomberg-style command efficiency and thinkorswim/TradingView linked layouts as reference behaviors, but implement original Atlas interaction patterns. Expert commands and saved workspaces should make recurring tasks fast while a non-programmer can complete baseline research without knowing the command language.

### 3.3 UI acceptance rule

For any core workflow, test both: (a) new-user completion with no code or unexplained jargon and (b) expert completion with shortcuts, scripting, and inspectable model definitions. Measure time-to-result, navigation steps, correctness, and retention of relevant context.

---

## 4. Replaceability and competition

**Competitive benchmark, not a copying plan:**

| Reference | Respect its strength | Atlas target |
|---|---|---|
| Bloomberg Terminal, Launchpad, BQuant, MARS, PORT | Data normalization, professional workflows, analytics, risk, Python, linked screens | Open research runtime with greater model portability, inspectability, and open methodological control |
| TradingView | Chart responsiveness, drawings, replay, alerts, scripting/community | Equally ergonomic charts plus models operating on broader financial/economic objects |
| thinkorswim | Options analytics, risk profiles, scanning, thinkScript | Editable pricing and risk models, connected directly to research and evidence |
| Interactive Brokers TWS | Multi-asset order/portfolio workflows | Optional permissioned execution and portfolio analytics; not prerequisite to research |
| Sierra Chart / Bookmap | Depth, microstructure, tape replay | Microstructure simulation and analysis when genuine granular data is available |
| Fincept Terminal | Native terminal, Python/QuantLib analytics, extensive modules | Unified typed finance IR, deep historical evidence and model validation, measured side-by-side |
| Neuberg | Flexible panels and broad discovery surface | Fewer, deeper real-data capabilities with strict provenance; avoid license contamination |
| OpenTerminal | Keyboard-first navigation, source fallbacks | Stable, authorized providers and stronger financial semantics |
| World Monitor | Multi-source OSINT, event correlation, maps | Source-to-issuer economic intelligence with investment-grade evidence discipline |
| OpenBB / OpenBQ | Provider abstraction and finance integration | Retain independent entities, timestamps, model semantics, computational substrate |
| LEAN / NautilusTrader / Qlib | Mature backtest, execution, ML workflows | Unified experimental definitions, evidence snapshots, model comparisons and apps |
| Open Source Risk Engine / QuantLib / Strata | Institutional pricing and risk mathematics | Validated multi-asset interoperability in one modeling environment |

The success criterion is **workflow substitution**, not identical source coverage or guaranteed superiority. For a defined use case, an evaluator should be able to complete the same professional research task in Atlas without leaving it, using data they are legally authorized to access, and compare quality against a documented incumbent workflow.

**Must remain clear:** Bloomberg's proprietary data contributions, research, messaging network, evaluated prices, and low-latency news cannot be made genuinely equivalent by writing code alone.

---

## 5. Architecture: the unified financial computing substrate

### 5.1 Reference architecture

```text
               EXPLORE       STUDIO       LAB       MONITOR
                  \            |           |          /
                     Atlas Adaptive Workspaces
               Search / Command / Code / Optional AI
                                |
                    Universal Research Objects
                Identity · Versions · Manifest · Permissions
                                |
                   Financial-Economic Compiler
             Parsing · Semantic Types · IR · Planning · Optimizing
                                |
                   Universal Execution Runtime
             CPU / SQL / Arrow / GPU / Numerical / Simulators
                 |          |          |          |
            Model Forge  Quant Lab  Risk/Prices  Econ Models
                 \          |          |          /
                Event/Probability + Decision Contracts
                    Experiment / Thesis / App OS
                Lineage · Validation · Replay · Sentinel
                                |
                    Financial-Economic Ontology
             Securities · Entities · Relationships · Events
                                |
                 TEMPORAL EVIDENCE + DATA FABRIC
          Source archive · As-of policy · Rights · Quality · IDs
                                |
         SEC / Public data / Licensed BYO / OSINT / User datasets
```

**The drawing shows dependency relationships, not a mandatory set of network services.** Many modules can initially run in one Python process and one local database. Subsystems become separate services only when tests establish isolation, scalability, failure-domain, or deployment benefits.

### 5.2 Architecture invariants

1. A computation may consume data only through typed, source-aware access contracts.
2. Each immutable source observation has an identity, provenance, time semantics, and original units.
3. Each output can identify its inputs, method version, assumptions, and engine version.
4. Models and UI are not entitled to invent stronger facts than the source evidence warrants.
5. A model's research results remain reproducible even if newer data or code arrives.
6. Backend choice does not alter semantics: reference behavior is tested across supported backends.
7. Data-provider authentication, rate limits, licensing, and rights are respected.
8. All user-created code runs with explicit sandbox and resource permissions.
9. All core deterministic workflows work without an LLM or proprietary hosted service.
10. The default local deployment remains low-friction and useful on CPU-only computers.
11. Market contract *wording*, settlement rules, payoff schedules, and venue are never discarded when normalizing event observations.
12. Probabilistic forecasts, tradable quotes, outcome classifications, causal effects, and recommendations remain separate typed objects.
13. Cross-domain intelligence is composed from opt-in packages using the same evidence/compiler/experiment system; no new permanent top-level application is required.

### 5.3 What Atlas owns versus integrates

**Own:** time-aware identity resolution, evidence/provenance, rights metadata, universal object and model manifest, finance semantic IR, dependency graph, experiment record, user experience, audit and integrity policy, interoperability contracts.

**Prefer to integrate:** data adapters, chart engines, numerical solvers, rates/derivatives libraries, optimization libraries, backtesting systems, ML trainers, local LLM runtimes, map renderers, and columnar computing engines.

**Do not automatically import:** source-available but noncommercial licensed repositories, AGPL components into incompatible distributions, proprietary TradingView chart libraries, or paid/reverse-engineered data feeds without authorization.

---

## 6. Universal Research Object System (UROS)

Every important research asset has a stable identity, declared type, version, source lineage, permissions, time semantics, and interface contracts. This is not one enormous table containing all object-specific fields. It is a shared **envelope** plus typed payloads and reference edges.

### 6.1 Canonical object families

**v1.1 extension:** Add future-compatible definitions for `EventDefinition`, `OutcomeSpace`, `Contract`, `SettlementPolicy`, `ForecastDistribution`, `ProbabilitySnapshot`, `QuoteObservation`, `PayoffFunction`, `CausalHypothesis`, `DecisionProblem`, `DecisionPolicy`, and `OpportunityAssessment`. The exact first schemas and validation requirements are specified in Sections 30 and 31. These are distinct objects, not aliases of a generic "prediction" record.


| Object | Meaning | Required specifics |
|---|---|---|
| `Entity` / `Security` / `Instrument` | Economic object and tradable claim | Issuer/security ID, identifiers, corporate-action rules, legal conventions |
| `Source` / `Evidence` | Original observation/document/claim | URI/hash, source terms, event and availability time, ingestion time, quality |
| `Dataset` / `FeatureSet` | Versioned structured observations | Schema, unit semantics, coverage, lineage, point-in-time policy, rights |
| `FinancialMetric` | Calculated or standardized quantity | Formula, fiscal period, valuation date, input evidence, units |
| `Model` | Deterministic/stochastic predictive or structural computation | Inputs/outputs, method version, parameters, constraints, artifacts |
| `Strategy` | Decision, portfolio, or order-generation policy | Universe, rebalance/event rules, risk constraints, permissions |
| `Simulation` / `Backtest` | Execution of a model in a stated world/time | Clock, state, scenario, execution assumptions, transactions |
| `Experiment` | Controlled attempt to evaluate a hypothesis | Data snapshots, baselines, search history, results, negative findings |
| `Thesis` | Argument about an economic/financial outcome | Evidence, claims, assumptions, catalysts, tests, failure conditions |
| `Workflow` | Directed set of authorized tasks | Dependencies, triggers, action boundaries, checkpoints |
| `ResearchApplication` | Reusable interactive package | Dependency manifest, panels, controls, code, rights, deployment |
| `Workspace` | View state and collaboration context | Layout, bindings, selected time/security, linked objects |
| `Monitor` / `Alert` | A maintained condition over objects | Trigger, threshold, source freshness, audit, user authorization |

### 6.2 Shared envelope, conceptual schema

```yaml
atlas_object:
  schema_version: 1
  object_id: atlas:model:uuid-or-content-id
  object_type: model
  object_version: 5
  created_at: 2026-11-04T00:00:00Z
  owner: local
  visibility: private
  license_and_rights: {execution: allowed, redistribution: inspect-dependencies}
  input_contracts: [dataset:revenue:v4, dataset:energy_prices:v7]
  output_contracts: [distribution:quarterly_margin:v1]
  availability_policy: strict_public_asof
  code_or_method_digest: sha256:...
  parameter_digest: sha256:...
  environment_digest: sha256:...
  dependency_edges: [evidence:..., model:...]
  validation_state: experimental
  quality_and_limitations: []
```

This is illustrative, not a frozen JSON schema. Implementations must publish machine-validatable versions and migrations.

### 6.3 Required object operations

`inspect`, `explain`, `resolve`, `use_as_input`, `fork`, `compare`, `execute`, `test`, `simulate`, `monitor`, `export` and `package` are capability-gated operations. Objects expose only relevant actions. A filing is not executable code; a model cannot automatically place trades.

A `ResearchApplication` is a versioned composition of object definitions, data source references, allowed UI components, declared permissions, and reproducible execution plans. It is not a zip file with unrestricted code that runs as administrator.

---

## 7. Data Fabric, Temporal Evidence Kernel, and source quality

Phase 1's **Security and Entity Master** and **Temporal Evidence Kernel** are preserved, not reimplemented. The financial data fabric expands around them.

### 7.1 Source classes

- **Financial filings and ownership:** SEC EDGAR, XBRL facts and instances, Forms 4, 13F, N-PORT when available, other regulators and issuer disclosures.
- **Market and reference data:** authorized equities, ETFs, fixed income, derivatives, commodities, FX, digital assets, exchange schedules, corporate actions and instrument definitions.
- **Macro and public policy:** FRED/ALFRED, U.S. Treasury, central banks, CFTC, IMF, World Bank, national statistics agencies, trade data.
- **Industry and regulatory:** FDIC/FR Y-9C, FINRA public datasets, EIA, federal procurement, patents, court/agency records where lawful.
- **Real-world intelligence:** NOAA, USGS Landsat, Copernicus, public infrastructure/geospatial data, suitable GDELT-like event sources, vetted research metadata.
- **Premium optional:** legally connected real-time market data, estimates, transcripts, derivatives histories, evaluated prices, newswires, execution feeds.
- **User sources:** local CSV/Parquet/Arrow, databases, approved APIs, spreadsheets, research documents, private licensed data.

Every source requires a registry record covering: owner, access method, freshness, retention, rights, coverage, resolution, survivorship, symbol conventions, corrections, release timing, rate limits, cost, and permitted downstream uses.

### 7.2 Four critical time dimensions

1. **Observation/effective time:** when the underlying measured event or financial period relates to.
2. **Publication/public-availability time:** when it was demonstrably available to an external researcher, with precision/uncertainty.
3. **Atlas ingestion time:** when a particular Atlas instance recorded the source.
4. **Revision/supersession time:** when a new version, correction, or later statement changes the available interpretation.

Optional exchange, vendor-receipt, simulation, and processing timestamps are separate. **Never replace an unknown public availability timestamp with a convenient earlier value.** Preserve exact/day/interval/unknown semantics. Default conservative point-in-time selection must exclude evidence not provably available by the cutoff.

### 7.3 Historical integrity

- Raw observations are immutable, with append-only revisions and cryptographic hashes.
- Distinguish annual, interim, year-to-date, and instant accounting values. Do not equate a filing reportDate with the period of every tagged fact.
- Historical ticker/issuer mappings and security survivorship use time-bounded evidence rather than current symbol tables.
- Historical price adjustments are labeled raw, split-adjusted, dividend-adjusted, or total return; no double-adjustments.
- Corporate actions have separate declaration, ex, record, payment, effective, and source-availability dates where relevant.
- Macro vintages preserve the distinction between observation period and release/revision dates.
- Provider disagreement is retained and inspectable. Missing coverage remains missing.
- User-specified and documented **public-as-of** and **Atlas-observed-as-of** semantics remain distinct.
- Historical research can be replayed from recorded snapshots, with explicit incompleteness flags if inputs were not archived.

### 7.4 Data quality as a first-class object

Quality reports should measure freshness, completeness, timeliness, source consistency, survivorship coverage, unit compatibility, accounting reconciliation, time precision, licensing, and outlier diagnostics. A single uncalibrated quality score is insufficient. APIs must expose individual failure reasons. Derived metrics inherit relevant input limitations.

### 7.5 Real data and synthetic data

**Event and forecast data requirements:** Preserve contract publication and amendment times; market trade/quote event time and the provider's delivery timestamp; model issue time, valid window, forecast horizon, target/event resolution time, and final adjudication time. Market data history must not be treated as historical order-book depth unless actual order-book events were archived. Forecast-vintage replay requires archived forecasts as *issued*, not later downloads of revised values. Absence of a validated publication clock must be visible to the user.


Synthetic data is essential for deterministic tests and demonstrations. It must always be machine- and human-labeled. Never place simulated data in a view that calls it a live market or show illustrative options surfaces as observed quotes. Data completeness and market freshness are displayed per instrument and source.

---

## 8. Financial-Economic Ontology and entity graph

**v1.1 ontology extension:** The graph must distinguish `Event` (world occurrence), `Outcome` (claim about the event), `Contract` (venue-specific legal payoff), `ResolutionRule` (authoritative adjudication), and `Forecast` (model-generated distribution). Linking two contract listings by title alone does not establish payoff equivalence. Graph edges describing causal mechanisms must be labeled `hypothesized`, `identified_under_assumptions`, or `experimentally_supported`, distinct from sourced ownership or geographic relationships.


Create a versioned ontology representing issuers, legal entities, securities, contracts, funds, portfolios, locations, facilities, suppliers, customers, products, energy assets, trading venues, governments, and real-world events.

Every relationship is an evidence-backed **assertion** with subject, predicate, object, source, time interval, method, and review status. Relationships can be `observed`, `reported`, `inferred`, `modeled`, `contradicted`, or `unresolved`; these are not interchangeable.

Required graph operations: query historical relationships as-of T, traverse sources, perform entity disambiguation, explain candidate matches, inspect conflicting assertions, find affected securities, and propagate structured *scenario assumptions* through explicitly supported economic models.

Do not automatically translate a news mention of two companies into a verified supplier/customer relationship. Do not treat geographic proximity as a contractual relationship. Avoid false precision and causal claims from correlation.

**Graph strategy:** start with relational assertion tables and indexes, using existing Phase 1 IDs and the reverse dependency index. Introduce a dedicated graph database only after real traversals show a justified need.

## 9. Data Rights Engine and sustainable open-source economics

Open source licenses for code do not automatically authorize redistribution of data, article text, newswire events, analyst estimates, fund holdings, or exchange products. The rights layer is mandatory for a commercially distributable research platform.

### 9.1 Dataset rights manifest

Every dataset and imported artifact declares applicable fields, with unknown values treated conservatively:

- License identity, provenance of the terms, effective version/date, attribution requirements.
- Personal/research/educational/commercial usage permissions where determinable.
- Rights to cache, retain raw responses, derive metrics, display, redistribute, publish, and train models.
- API redistribution clauses, user-consent requirements, private data restrictions, geographic restrictions and expiry.
- Whether exported models or applications can include raw data or only provider references.
- Whether a data connection is user-held or centrally licensed.

When rights are ambiguous, block auto-redistribution and prompt for review. Data Rights Engine is a policy/evidence system, not a substitute for legal advice.

### 9.2 Business model

- **Community:** Free open-source computation core, local terminal, modeling, backtesting, ML integration, available data adapters, SDK, local applications, supported local storage.
- **Data connections:** User-supplied entitlements; optional fee-for-access commercial data where Atlas obtains lawful agreements. The same core calculations run with either free or paid data.
- **Hosted convenience:** Optional managed synchronization, secure compute, remote GPUs, object storage, backup, collaboration, governance, uptime support and API capacity.
- **Enterprise:** Optional private deployments, audited access controls, SSO, support, managed services, compliance tooling, data integrations. Essential mathematical algorithms are never locked behind an enterprise tier.

No promise that the software can be hosted or operated for zero cost. Electricity, hardware, bandwidth, premium data, newswire rights, and GPUs remain real expenses.

### 9.3 Open-source legal policy

A permissive project license, such as Apache-2.0, is a reasonable starting candidate for Atlas, **subject to legal review and dependency audit**. The choice must be explicitly approved before release. Maintain per-component SPDX attribution, notices, third-party SBOMs, and license-compatibility checks in CI.

- **Neuberg:** BSL 1.1 with perpetual noncommercial restrictions per repository license reviewed in November 2026. Treat as an interface study; do not copy its code into a commercially usable permissive Atlas core.
- **Fincept Terminal and World Monitor:** AGPL obligations and any additional terms need review before integration. Architectural inspiration is not permission to relicense code.
- **OpenBB/OpenBQ:** Upstream stewardship is changing; verify maintainership, latest licensing, deployment implications, and supported provider APIs before dependency decisions.
- **TradingView:** Lightweight Charts is Apache-2.0 and has attribution/notice obligations. Advanced Charts and Trading Platform products are proprietary and not substitutes for freely redistributable open-source code.
- **ORE / QuantLib / suitable solver libraries:** Evaluate published permissive licenses, build complexity, and test coverage on a per-component basis.
- **Financial data:** Provider terms always govern, regardless of whether the adapter itself is MIT, Apache, BSD or AGPL licensed.

---

## 10. Financial-Economic Compiler: the central original engineering asset

The **Financial-Economic Compiler (FEC)** transforms financial equations, model graphs, code interfaces, scenario definitions, and visual compositions into well-typed, evidence-aware executable plans. It is a compiler for *financial meaning and reproducibility* before it is a speed optimizer.

### 10.1 Frontends

- Atlas typed visual model graph.
- Financial equation editor with declared symbols and units.
- Python SDK and registered Python operators.
- SQL/query language for approved analytical datasets.
- An optional Atlas DSL for finance, time, units, portfolios, scenarios and constraints.
- Optional AI-generated model proposals, which must pass all the same schema and semantic validation.

**Never require a bespoke language for simple models.** Users may compose ordinary Python and Arrow/NumPy/Polars operations through validated adapters. The IR provides interoperability and lineage; it is not expected to compile arbitrary Python semantics.

### 10.2 Typed Intermediate Representation (IR)

**v1.1 type extensions:** Define forward-compatible `Event[DefinitionVersion]`, `Outcome[Space]`, `BernoulliProbability[Target]`, `CategoricalDistribution[OutcomeSpace]`, `ContinuousForecast[Unit,Horizon]`, `MarketQuote[Venue,Contract,Side]`, `Payoff[Currency,SettlementPolicy]`, `Decision[ActionSpace]`, and `CausalEffect[Estimand,Assumptions]`. They may share execution machinery with financial types but must never be silently interchangeable. Probabilities must satisfy finite/domain and outcome-coherence checks. A quoted price is not automatically a calibrated probability; a venue payoff is not a physical event; a modeled correlation is not a causal effect.


At minimum, nodes specify: operator ID and version; input/output semantic types; financial units; shape/frequency; temporal availability; precision; deterministic/stochastic flag; statefulness; side effects; declared computational cost; execution backend requirements; dependency identity; and lineage output policy.

Examples of semantic types:

- `Money[USD]`, `Shares`, `Price[USD/share]`, `Rate[annualized, convention]`, `Probability`, `Quantity[kWh]`, `PhysicalCapacity[MW]`.
- `AccountingFlow[issuer, period_start, period_end]` versus `AccountingStock[issuer, as_of]`.
- `BarSeries[security, venue, interval, adjustment]` versus `TickSeries[security, feed]`.
- `Curve[currency, index, valuation_date, day_count]`, `VolSurface[underlying, quote_convention, date]`.
- `Forecast[variable, horizon, distribution, model_version]` versus `Observed[variable, source]`.
- `Event[effective_time, public_time, source]`, `Portfolio[positions, pricing_time, numeraire]`.

### 10.3 Semantic validation

The compiler MUST reject or require explicit conversion for:

1. Mixed currencies without a source-backed FX conversion and valuation time.
2. Incompatible fiscal durations, periods, and flow/stock arithmetic.
3. Mixing pre-split price series with post-split share counts without declared adjustment.
4. Modeling observations as publicly known before their justified publication time.
5. Feeding model predictions into fields labeled observed facts.
6. Incompatible instrument conventions such as day count, settlement or compounding without conversion.
7. Undeclared future information, prohibited data rights, untrusted side effects, or unsafe code capabilities.
8. Missing training/inference schema compatibility in ML graphs.

Where proof is not feasible statically, emit a declared runtime check and an explicit uncertainty/coverage limitation. The IR must never imply that arbitrary real-world causal claims are proven by type checking.

### 10.4 Compiler pipeline

```text
User model / equation / visual graph / approved generated model
  -> parse / schema validation
  -> entity + units + temporal + rights resolution
  -> strongly typed versioned IR
  -> dependency + effect + state + provenance analysis
  -> execution planning / legal optimizer rewrites
  -> selection of compatible CPU/SQL/GPU/solver/backtest backends
  -> artifact cache and execution
  -> validation, uncertainty metadata, lineage, versioned output
```

### 10.5 Optimization and correctness

Potential optimizations: column/filter pushdown, shared feature materialization, caching with versioned keys, vectorized operator fusion, common-subexpression reuse, parallel independent graphs, efficient incremental recomputation, and CPU/GPU planning. Optimization is allowed only if semantic and numerical invariants remain satisfied. Benchmark a reference implementation against each optimized backend.

**Cache keys** must account for: source snapshots, release/availability policy, model/op version, parameters, code and library versions, relevant market conventions, seed, rights/visibility, backend precision, and any effectful inputs.

### 10.6 Reverse dependency and reactive recomputation

Existing Phase 1.1 reverse-dependency indexing is the foundation. Extend it to include dataset versions, features, model runs, registered research applications, and monitors. A new filing should invalidate only affected deterministic outputs. Retraining statistical/ML models must follow an explicit policy and controlled re-evaluation; it is not a side effect of a document appearing.

### 10.7 FEC benchmark gate

Show semantic equivalence across: (a) native formula, (b) visual composition, and (c) Python SDK adapter for the same tested financial result. Demonstrate that incorrect currency, period, availability, or adjustment use is rejected. Show exactly which nodes become stale when an upstream filing is amended. Measure no-op cache reuse and targeted versus full recomputation.

---

## 11. Universal Execution Runtime and storage/compute architecture

The runtime coordinates compatible compute engines while maintaining common identity, job, provenance, and artifact contracts.

### 11.1 Engine families

| Executor | Primary use | Candidate technologies |
|---|---|---|
| Transactional/data-core | Evidence writes, identity, permissions, registry | Existing Python + SQLite first |
| Analytical SQL | Screeners, large joins, historical factors, feature creation | DuckDB, Parquet, Arrow, optionally Polars |
| Vectorized numerical CPU | Statistics, transformations, portfolios, small/medium models | NumPy, SciPy, optimized Python/C++ routines |
| Quantitative pricing/risk | Curves, instruments, sensitivities, Monte Carlo, XVA where supported | QuantLib, ORE, Strata evaluated as plugins |
| Optimization | LP/MIP/CP, convex, constrained allocation | CVXPY, OR-Tools, suitable open solvers |
| ML CPU/GPU | Feature transforms, inference, training, neural architecture work | PyTorch, compatible trainers, TorchInductor/Triton |
| Event-driven trading | Bars, orders, portfolio accounting, exchange events | LEAN or NautilusTrader adapter, after bake-off |
| Microstructure simulator | Tick/depth event processing, limit-order book, latency | NautilusTrader/ABIDES and targeted simulation modules |
| Economic/graph simulation | Structural models, scenario propagation, network shocks | SciPy sparse, graph packages, specialized solvers |
| Document/OSINT research | Parsing, retrieval, extraction, source-backed reasoning | Local pipelines, search index, optional LLM adapters |

**Run-time invariant:** external engines may be different languages and processes, but their outputs must declare methodological assumptions, versions, input snapshots, and limitations in a common Atlas envelope.

### 11.2 Hardware policy

CPU-only is a supported baseline. GPUs are optional acceleration, not a correctness requirement. The compute planner considers memory footprint, transfer costs, precision constraints, compile overhead, batch size, throughput, and measured hardware-specific benefits.

GPU candidates to benchmark: RAPIDS cuDF, Polars GPU, PyTorch compilation/Triton, custom kernels only where an existing backend is demonstrably inadequate. An advertised hardware acceleration speedup never substitutes for an end-to-end benchmark.

### 11.3 Logical storage tiers

- **Metadata and evidence:** transactional and versioned; SQLite for local single-user; optional production DB later.
- **Analytical time series:** Parquet/Arrow/DuckDB for broad local query workloads.
- **Cold artifacts:** content-addressed files/object storage for filings, reproducible experiments, model checkpoints and large tensors.
- **Hot subscriptions:** optional in-memory event buffers and streaming layer for live provider data.

This is a logical design, not a mandate to run four databases on day one. Maintain clean conversion contracts. Introduce Iceberg, distributed schedulers, online feature stores, or dedicated graph infrastructure only after measured need.

### 11.4 Jobs, events, and failure semantics

Every long-running job has a stable ID, state machine, idempotency key, quota, resource budget, cancellation, checkpoints, retry policy, and structured logs. Preserve source request/response hashes when legally possible. No job should silently succeed if required source coverage is missing. Historical ingestion should remain recoverable after crashes. Deterministic replay cannot be promised when original external responses were never archived.

For live data, explicitly specify event order, dropped packet behavior, backfill, source freshness, exchange timestamps, reordering windows, and reconciliation after outages. Exact-once delivery is not assumed without proof.

---

## 12. Model Forge: unrestricted model creativity with enforced contracts

The **Model Forge** is where users build new algorithms, mathematical relationships, valuation systems, indicators, AI models, structural business models, and entire financial programs.

### 12.1 Four authoring paths

1. **Configure:** existing models with transparent parameters and assumptions.
2. **Compose:** drag-and-connect typed datasets, transformations, models, optimizers, scenarios and outputs.
3. **Code:** Python/SQL/SDK, compatible libraries, custom operators in a sandbox.
4. **Describe:** optional AI drafts editable model specs and applications, with no privileged bypass of validation.

An equation editor is also offered for symbolic expressions. All supported methods translate to common model specifications or wrapper contracts; unsupported dynamic code is tracked as a typed external operator with declared effects, not falsely compiled into fully understood IR.

### 12.2 Model families

**Fundamental and equity:** three-statement operating forecasts, segment and product models, DCF, reverse DCF, residual income, sum-of-the-parts, capital allocation, owner earnings, dilution, M&A, credit leverage, liquidation, free cash flow, peer and relative valuation, market-implied expectations, probabilistic valuation, factor exposure.

**Technical and market:** full OHLCV charting, VWAP with correct frequency input, momentum, mean reversion, volatility, liquidity, order flow, chart patterns, custom studies and alerts.

**Statistical/econometric:** OLS/GLS, regularization, PCA, bootstrap, time-series forecasts, ARIMA/VAR, state-space/Kalman, GARCH, regime switching, cointegration, Bayesian hierarchical models, distributional forecasting, hypothesis and multiple-testing corrections.

**Mathematical:** symbolic regression, constrained nonlinear optimization, stochastic differential equations, Monte Carlo/quasi-Monte Carlo, sensitivity/automatic differentiation where suitable, convex and mixed-integer optimization, sparse linear algebra, numerical integration, robust optimization.

**ML:** gradient boosting, tree ensembles, sequence forecasting, time-series transformers, graph neural networks, self-supervised financial representation learning, anomaly detection, uncertainty/calibration, automated feature search.

**Multi-asset:** bonds, rates, FX, derivatives, commodities, credit, volatility surfaces, fixed-income term structures, portfolio risk and allocation, instrument-specific models.

**Real-world economics:** capacity, energy, production, logistics, input-output networks, supply-chain constraints, physical infrastructure, demand, regulatory shocks, macroeconomic models.

### 12.3 Versioned mathematical model definition

A model must declare domain, assumptions, governing equations or external method, inputs/units, required data granularity, historical availability, parameters, randomness/seed, output shape, evaluation tests, numerical tolerances, evidence/reference implementation, limitations, and performance envelope.

A created model may have the statuses `draft`, `experimental`, `validated_for_named_tests`, `reviewed`, `deprecated`, or `invalidated`. Avoid a generic global label of 'mathematically proven' for statistical or empirical models.

### 12.4 Branching and Model Genetics

Users can fork model graphs, change components, compare versions, record all tried variants, and preserve failed experiments. Automated model discovery may use symbolic regression, Bayesian optimization, evolutionary search, constrained architecture search, and active experiment selection.

**Critical overfitting guard:** validation data reused to select successive candidates is part of the development process; Atlas must reserve untouched or sequential forward evaluation data and account for the complete search history.

### 12.5 Version 2 model-catalog and composition requirements

Sections 36 and 37 make the universal model catalog and Model Composition Engine explicit product contracts. Every compatible built-in or custom method must be reusable in a larger typed graph, including sequential, parallel, hierarchical, conditional, residual and ensemble composition. A composed graph can become a new versioned Model, be compared in Lab, audited, saved and turned into a ResearchApplication. The names in the catalog are desired coverage targets, not evidence that every method is implemented or effective. ICB-21 through ICB-23 are the associated release gates.


---

## 13. Quant Lab, Alpha Foundry, and historical strategy simulation

Atlas must support creative strategy authoring, rigorous evaluation, and deep simulation without requiring real trading access.

### 13.1 Three simulation fidelities

| Fidelity | Purpose | Mandatory disclosures |
|---|---|---|
| Vectorized/factor research | Fast broad candidate screening and portfolio math | Timing convention, rebalancing, survivorship, adjustments, estimated costs |
| Event-driven portfolio/backtest | Chronological market and order decisions | Order model, latency, fills, borrow, slippage, fees, dividends, splits, exchange calendar |
| Order-book/microstructure | Depth, queue position, exchange mechanics | Granular licensed inputs or clearly synthetic order-book assumptions; simulator calibration |

A vectorized study does not automatically establish that an execution-sensitive market-making strategy is feasible. A synthetic order book cannot establish execution performance on an actual exchange.

### 13.2 Strategy API

A strategy declares universe construction, data entitlements, features, decision schedule, position sizing, portfolio and risk rules, execution assumptions, benchmark, instrument restrictions, and outputs. It can specify target weights or simulated orders. Real broker routing is a separate `TradingCapability` requiring explicit user authorization and complete risk controls.

### 13.3 Research methods

Support single-asset and multi-asset factor studies, cross-sectional analysis, event-driven strategies, statistical arbitrage, time-series momentum, allocation, derivatives research, credit/rates strategies, and ML-based signals as reliable data and simulation rules become available.

### 13.4 Mandatory anti-bias and realism checks

- Universe construction as known at each date; explicit delisted coverage and survivorship limits.
- Time-of-information constraints on every input and feature.
- Corporate actions and dividend handling; delistings, suspensions, and stale prices.
- Transaction costs, spreads, liquidity, borrow/funding, partial fills and market impact assumptions.
- Data revisions, adjusted-price provenance, calendar/session alignment.
- Label overlap, purged or embargoed validation when justified, sequential evaluation.
- Hyperparameter search multiplicity, factor redundancy, sensitivity to plausible costs and market regimes.
- Capacity, turnover, drawdowns, tail exposures, factor benchmarking and stress conditions.
- Independent reconciliation of portfolio cash, positions, P&L, fees and corporate actions.

### 13.5 Research Credibility Report

Each experiment produces measured performance and a visible audit: annualized returns as defined, risk, benchmark comparison, test sample, true test count when known, feature publication limitations, cash accounting checks, model-selection history, capacity assumptions, sensitivity plots, and reproducibility digest. No ungrounded 'alpha score' that certifies profitability.

### 13.6 Engine reuse policy

**v1.1 cross-asset simulation rule:** Event contracts may eventually use Quant Lab's chronological simulator, accounting, experiment ledger, and risk reports, but require distinct order books, payoffs, resolution states, collateral/margin assumptions, outcome correlation, lifecycle, and venue-specific fee engines. Sports pick-entry contests have non-exchange payout and cancellation structures and must not be coerced into exchange contracts. Begin read-only and paper-only; never infer historical executable fills from midpoint charts.


Benchmark LEAN versus NautilusTrader for a small set of exact reference trades, market data formats, replay behavior, transaction/corporate-action handling, configuration, isolation and runtime. Use an adapter around the selected engine; allow a second backend later if it adds material value. Do not rewrite a mature order simulator to create the appearance of original infrastructure.

---

## 14. Institutional valuation, fixed income, derivatives, and portfolio risk

This is a full mathematical research program, not a list of surface-level widgets.

### 14.1 Valuation infrastructure

Detailed company models must support cash flow forecasts, operating drivers, three-statement checks, capex/depreciation, working capital, leases, share dilution and buybacks, financing/debt schedule, cost of capital, terminal outcomes, scenarios, valuation contributions and sensitivity. Inputs and assumptions are separate, explainable objects.

The **Reality-to-Market** solver can infer feasible sets of market-implied assumptions under a given model. It must report non-identifiability, dependence on discounting, and the influence of other plausible assumptions.

### 14.2 Rates and fixed income

- Cash-flow schedules, settlement, accrued interest, calendars, day-count and compounding rules.
- Yield curves: observed inputs, instrument conventions, bootstrapping, interpolation, extrapolation and pricing time.
- Duration, convexity, key rate risk, term structures, credit spread measures and scenario risk.
- Floating rates, swaps, caps/floors, swaptions and model conventions as supported.
- Credit curves, default/hazard models, recoveries, issuer/portfolio credit sensitivity.

### 14.3 Derivatives

- Contract terms, exercise, settlement and payoff definitions.
- Suitable pricing methods: analytical solutions, trees, finite differences, Monte Carlo, stochastic volatility, and numerical calibration.
- Greeks, volatility surfaces with quote convention, risk aggregation, cash and collateral treatment where supported.
- Exotic and multi-asset derivatives only when data and numerical validation justify scope.

### 14.4 Portfolio research

- Trade/position/cash accounting, multi-currency numeraire, benchmark/factor risk, covariance conditioning, drawdown and liquidity.
- Attribution, scenario/stress exposure, robust optimization, constraints, turnover and realistic risk budgets.
- Multi-asset simulations and tail metrics such as VaR/CVaR with methodology transparency.

### 14.5 Reference implementation strategy

Use QuantLib and Open Source Risk Engine as primary candidates for vetted pricing and risk capabilities, with OpenGamma Strata as another benchmark where appropriate. Each Atlas adapter must map financial conventions precisely. Unit tests and a published instrument-specific reference pack are mandatory; matching one example does not validate an entire asset class.

---

## 15. Atlas Intelligence: a real brain, not a mandatory chatbot

**Atlas Intelligence** combines (a) optional language reasoning, (b) specialized statistical and neural learning, (c) experiment planning and meta-learning, and (d) user-specific research context. These are independently testable services.

### 15.1 Four intelligence subsystems

1. **Research Planner:** translates goals into explicit hypotheses, tools, datasets, baselines, alternative explanations, estimated costs and bounded plans.
2. **Financial Learning Models:** task-specific prediction and representation learning for earnings, credit, volatility, economic series, anomaly detection and relationship hypotheses.
3. **Scientific Discovery System:** proposes features and equations, prioritizes experiments, tracks failures, runs ablations and challenges apparent successes.
4. **Research Memory and Personal Context:** stores tested hypotheses, versioned experiments, research conventions and opt-in user preferences with privacy boundaries.

### 15.2 AI interaction levels

- **Passive:** contextual availability and relevant facts, no interruptions or unapproved resource consumption.
- **Assistive:** user explicitly asks Atlas to research, explain, design or run an experiment.
- **Bounded autonomous:** approved recurring research or monitoring with allowed sources, time, cost, permissions, data retention and cancellation controls.

AI may propose code, estimates, visualizations and research plans. Financial calculations and model execution remain controlled by deterministic or explicitly declared stochastic engines. AI assertions require citations, confidence caveats and validation; fabricated source references are treated as defects.

### 15.3 Local and optional models

Evaluate local inference runtimes and open-weight language models, but record actual model-weight licensing and hardware requirements. External API providers are optional. A GPU may accelerate useful workloads; CPU-only model execution or manual workflows remain valid. Do not prioritize pretraining a financial foundation LLM before benchmarks show a justified task-specific gap.

### 15.4 Financial representation learning

Investigate learned representations of companies, securities, financial statements, textual evidence and economic relationships. Candidate inputs may include accounting, market, document and graph features. Training must preserve point-in-time boundaries, missingness, universe coverage and licensing. Evaluate on multiple downstream tasks against simple feature baselines; do not confuse improved embeddings with improved trading returns.

### 15.5 Research memory without selection bias

Every candidate experiment, including failed ones, is stored. Meta-learning and automated model search must document their training and selection data. Future evaluation periods cannot be repeatedly reused as pristine holdouts. Memory of failed ideas should reduce repeated work, not certify a promising strategy.

### 15.6 Model Auditor

**v1.1 research brain:** Add forecasting self-evaluation, calibration drift detection, uncertainty decomposition, source conflict detection, and research-policy memory. The optional LLM may propose a contract match, causal graph, or trade hypothesis, but deterministic parsers, typed validation, independent verification, and user controls decide whether the object is accepted. The AI must be able to state that the required evidence does not support a recommendation.


Automatically check accounting identities, input ranges, periods, source provenance, numerical accuracy, statistical validation, model drift, alternative hypotheses, scenario sensitivities, data leakage, and simulation assumptions. Report evidence and uncertainty, not decorative grades.

## 16. Global OSINT, news intelligence, and the Economic Reality Engine

Atlas's economic intelligence must answer **financial questions about real economic systems**. It is not merely a map of geopolitical headlines.

### 16.1 Source and investigation capabilities

Ingest and index available, legally usable sources involving corporate relationships, facilities, electricity and energy, transport, maritime/aviation signals, public procurement, government filings, patents, scientific papers, regulation, weather, environmental change, public demographic data, and satellite-derived observations. Support publication history and entity resolution as deeply as practical.

World Monitor, OpenOSINT, selected DeepDive projects, GDELT and mature geospatial tools are reference designs. Reuse depends on source rights, maintainability and code licenses. A map viewer can use standard tools such as MapLibre, deck.gl and open geospatial formats without adopting an entire AGPL application.

### 16.2 News intelligence

Atlas should support authorized RSS/API/public news sources and optional licensed wire feeds. Ingestion can perform source attribution, deduplication, entity linking, clustering, geographical tagging, novelty detection, article-to-filing cross-reference, and optional sentiment/classification.

**News latency must be measured honestly** as source publication to Atlas arrival and UI display, using observable timestamps. An app that polls Yahoo or Google RSS every second is not equivalent to a sub-second professional newswire. Clearly state event coverage and lag. Avoid building a business dependent on scraping protected news products.

### 16.3 Economic Intelligence Graph

Create source-backed economic edges such as `facility owned by legal entity`, `entity issued security`, `company reports supplier`, `contract awarded to entity`, `region has energy price series`, and `asset exposed to operating scenario`. Support uncertainty, evidence conflicts and dated relationship snapshots.

### 16.4 Economic Reality Simulator

A scenario is a versioned program with: initial world state, economic network, observed values, model assumptions, shocks, uncertainty distributions, boundary conditions, calibration data and output contracts. The simulator may combine structural equations, sparse network models, differential/difference equations, Monte Carlo, and neural forecasts. It must distinguish a *scenario result* from a *prediction of reality*.

Example: energy price shock -> identified facilities -> estimated power contracts/consumption -> unit cost and operating leverage -> modeled margin -> cash flow -> valuation and credit impact. Missing contract information is uncertainty, not permission to assume spot-price exposure.

### 16.5 Digital twin boundaries

Industry/facility-level digital twins require observed geometry, capacity, utilization, prices and validation. When these are unavailable, label outputs as simplified structural scenario models rather than digital twins. Do not claim physical-system realism without calibration or empirical evidence.

### 16.6 Cross-domain intelligence benchmark

**v1.1 boundary:** New domain packs cover event intelligence, scientific/technical diligence, venture/private-company research, property/infrastructure, regulatory intelligence, and selected weather/sports forecasting. Each pack must reuse the shared temporal evidence, entity registry, compiler, model registry, and experiment system. OSINT source licenses and privacy restrictions travel into every derived artifact. No inference of misconduct from a statistical anomaly without sourced investigation.


A reusable research application should investigate an energy or supply-chain event, discover relevant public evidence, identify affected entities, build alternative scenario assumptions, compute impact with uncertainty, and trace every reported relationship and result back to a source or explicit modeled assumption.

---

## 17. Research Operating System, Time Capsule, and Sentinel

### 17.1 Research lifecycle

Each investigation is a durable, versioned **Research Project** with a question, decision context, hypotheses, evidence set, methods, assumptions, candidate models, experiments, challenges, conclusions and unresolved limitations. A negative result is a first-class outcome.

### 17.2 Historical Research Time Capsule

Preserve dated research environments when rights allow: available evidence, security universe and identity, market observations, model/configuration versions, code, random seeds, dependencies, clocks, result artifacts and research notes. Provide two explicit replay modes:

- **Historical knowledge reconstruction:** use the information Atlas can substantiate was public at the selected time.
- **Execution reproduction:** rerun a recorded computation with archived data and compatible execution environment.

The former is not proof that Atlas actually ingested that source in the past; the latter is not proof the original historical market had a complete data universe.

### 17.3 Executable theses

A thesis has claims linked to evidence, valuation or causal assumptions, a model graph, falsification criteria, measurable monitoring conditions, expected events, alternative explanations, and update history. New evidence may mark parts stale but must not silently rewrite the thesis or approve new trading actions.

### 17.4 Research Sentinel

Monitor source updates, dependency changes, model drift, new filing facts, economic events, stale outputs and explicitly user-defined thresholds. Group alerts by research significance, disclose source freshness and confidence, avoid notification floods, support approval/cancellation and keep a complete audit trail.

### 17.5 Research publishing

**v1.1 decision trace:** An opportunity/research report must disclose the exact target, objective, forecast timestamp, alternative scenarios, model/data vintages, costs and liquidity where relevant, action permissions, and what would change the conclusion. A monitoring agent creates a proposed re-evaluation or stale-state notification, not an unreviewed financial action.


Export notebooks, code, model definitions, charts, reports, data manifests, static evidence links and self-contained Research Applications, subject to rights. Where raw data cannot be redistributed, package a reproducible fetch manifest or a rights-aware reference instead.

---

## 18. Financial Application Compiler and plugin ecosystem

The **Intent-to-Workspace Compiler** converts typed application/view specifications into interactive user interfaces. It is separate from the financial computation compiler but shares the same object and schema contracts.

### 18.1 App composition

Users can combine source connectors, models, input controls, visualizations, reports, tables, maps, scheduled workflows, alerts, and sandboxed custom code. Support reusable templates but never force users into a fixed list of applications.

### 18.2 Declarative application manifest

An app package declares: app identity and version, required object types, data entitlements, permissions, executable graphs, UI components and bindings, resource limits, public availability policy, output rights, and deployment target. The UI renderer validates before mounting. Do not treat a model-generated JSON file as inherently safe.

### 18.3 Community ecosystem

Support official and third-party connectors/models/plugins, signed package metadata, reproducible builds where practical, compatibility tests, permission manifests, moderation and abuse reporting, stable SDK APIs, and separate release channels. Extensions must not access private datasets or place live trades without specific authorization.

### 18.4 Portability

A model should be portable across Studio, Lab, and custom applications. Exports must document unavailable external assets and nonredistributable dependencies. Different interface modes should execute the same model rather than duplicate calculation logic in frontend JavaScript.

---

## 19. API, SDK, scripting, and extension contracts

Expose a documented API that supports:

- Entity and security discovery.
- Source registration, market/fundamental data access and historical queries.
- Evidence/X-Ray and company filings.
- Typed metrics, IR validation, compilation and execution.
- Model registry and artifacts.
- Feature store and ML dataset snapshots.
- Experiments, backtests, simulations, pricing/risk jobs.
- Research projects/theses, version comparisons, alerts.
- Watchlists, portfolios, workspaces, research applications.
- User permissions, resource quotas and source-rights inspection.

Default local access must remain loopback-only; public exposure requires authentication, authorization, session security, rate controls and an explicit deployment mode.

Provide a Python SDK early, a stable TypeScript client for the UI, machine-readable OpenAPI where suitable, and eventually Atlas DSL syntax with reference documentation. All public APIs and artifact types are versioned. Breaking changes require migrations or compatibility periods.

**Scripting principle:** Pine/thinkScript-like convenience for indicators and chart studies is valuable, but the native language should not be limited to charts. Financial and economic computations must support arbitrary compatible data objects, not only OHLC arrays.

---

## 20. Security, privacy, safety, and operational governance

**Event-domain security rule:** All prediction-market, sportsbook, fantasy, or similar adapters default to unauthenticated public research where licensed, and any account-connected or real-money action is a distinct separately authorized, jurisdiction- and age-eligible capability. Never circumvent regional restrictions, access controls, robots policies, or rate limits. No scraping of services whose terms prohibit it. Geolocation or identity requirements cannot be spoofed. Account secrets belong in a secure connector layer, never model manifests or public applications. The open core must remain valuable without any such accounts.


- **Default local-first:** no account required for local use; optional accounts for managed services and collaboration.
- **Secrets:** OS keychains or appropriately secured local/hosted secret management; never commit keys or expose them in app manifests or diagnostics.
- **Sandboxing:** custom and AI-generated code executes in containers/process isolation with restricted filesystem, network, CPU/GPU, time and memory. No unrestricted browser-side code evaluation.
- **Access control:** permissions are checked at source acquisition, model execution, artifact export, share and trading actions. Future collaboration uses least privilege and auditable roles.
- **Trading:** research/paper execution is default. Real-money connectivity requires explicit per-account authorization, order/risk limits, confirmation policies, killswitch, secret isolation and regulatory/legal review; never run an unbounded agent with trading permissions.
- **OSINT:** use lawful public sources, honor access policies, protect personal information, and prohibit unauthorized surveillance or credential abuse. Financial entity intelligence does not authorize unrestricted investigation of private individuals.
- **Model risk:** mark unvalidated estimates, simulations and probabilistic outputs. Never present LLM outputs or AI sentiment as authoritative trading recommendations without methodological context.
- **Availability:** data quality and source failures must be visible; if source is stale, downgrade display state instead of inventing freshness.
- **Supply chain:** pinned dependencies, SBOM, license scan, vulnerability monitoring, CI and reproducible builds where practical.
- **Observability:** structured traces, ingestion health, query latency, cache staleness, model runs, audit logs, and privacy-preserving diagnostics.
- **Research transparency:** disclosures that model performance is historical and non-guaranteed, with out-of-sample evaluation and method descriptions.

---

## 21. Stack evolution and implementation discipline

### 21.1 Preserve the reported Phase 1/2 foundation

The user-provided agent reports describe a Python 3.12 core, SQLite metadata and temporal evidence, REST/FastAPI, React/TypeScript/Vite UI, TradingView Lightweight Charts, and versioned data/migration contracts. **Treat these as agent-reported status until independently audited in the actual repository.** Do not rebuild them just because this vision is more ambitious.

### 21.2 Preferred evolution

| Layer | Near term | Long term only if justified |
|---|---|---|
| Evidence/metadata | Current SQLite temporal core | Optional PostgreSQL or another transactional store for concurrency/teams |
| Historical analytics | Arrow/Parquet, DuckDB/Polars | Larger distributed table format/engine when workloads demand it |
| API | Existing Python HTTP and typed schemas | Horizontal workers and streaming endpoints if necessary |
| Frontend | Existing React/TypeScript terminal | More sophisticated renderer and desktop packaging if valuable |
| Charts | Lightweight Charts with attribution | Extend using original tools and independent rendering for unsupported interactions |
| Finance computation | Python + validated numerical libraries | Rust/C++ compiled operators for profiled hotspots |
| Quant execution | Adapter around selected proven engine | Multiple backends only if semantic parity is tested |
| ML | PyTorch and experiment/version registry | GPU/remote workers; specialized foundation models where justified |
| OSINT | Source adapters + relational relationship graph | Dedicated graph/search/geospatial services when measured |
| Jobs | Local process and durable queue | Cluster scheduler only for demonstrated multi-user/large experiments |

**Rule:** Complexity must buy correctness, capability, performance, isolation or ease of extension. A system can be internally sophisticated without being distributed from day one.

---

## 22. Institutional Capability Benchmark (ICB)

The institutional replacement claim is measured in a public **Atlas ICB** suite. No performance superiority is asserted without running equivalent tasks under declared data rights and hardware conditions.

### 22.1 Required flagship research benchmarks

| Suite | Task | Independent validation and pass conditions |
|---|---|---|
| **ICB-01 Equity Research** | SEC data -> three-statement model -> reverse DCF -> comparable company and scenario view | Check accounting identities, period selection, filing provenance, numerical reproducibility and scenario sensitivities |
| **ICB-02 Fixed Income/Risk** | Build a curve, value bonds and vanilla rate instruments, calculate sensitivities and stress | Match published test vectors and compatible QuantLib/ORE references within declared tolerances |
| **ICB-03 Quant ML** | Build factors, train statistical and neural baselines, run point-in-time backtest | No deliberate future leakage; validation, selection history, costs, cash/position accounting, reproducible results |
| **ICB-04 Economic Intelligence** | Public energy/infrastructure signal -> linked issuer -> modeled financial outcomes | Every entity edge source-backed or explicitly inferred; assumptions and uncertainty shown |
| **ICB-05 Application Creation** | Describe/build a new model-based financial application | Same outputs through code, visual canvas and application; save/restart/export/restore |
| **ICB-06 Time Machine** | Reconstruct company knowledge before/after amendment and macro revision | Historical outputs exclude subsequent facts; missing precision/coverage identified |
| **ICB-07 Data Rights** | Build/export an app mixing public and restricted sources | Block unauthorized raw redistribution, preserve legal provenance and attribution |
| **ICB-08 GPU/CPU** | Factor creation, neural training, Monte Carlo and screeners on realistic datasets | Publish throughput/latency/memory, parity tests, transfer overhead and hardware |
| **ICB-09 OSINT Research** | Investigate contracts, events and corporate relationships | Distinguish observed/inferred/model-generated claims, preserve source/date lineage |
| **ICB-10 Full Reproduction** | Re-run an archived research application with preserved inputs | Reproduce declared deterministic outputs or explain numerical/environment differences |

| **ICB-19 Real Estate Underwriting** | Take an evidence-backed rental property or user-authorized rent roll from acquisition to annual cash flows, debt, sale and investor return | Independently reconcile leases, vacancy, concessions, NOI, capital expenses, amortization, DSCR, equity cash flow, IRR and exit; distinguish source facts from assumptions |
| **ICB-20 Property Risk and Spatial Evidence** | Underwrite a real estate asset under regional housing, hazard, financing and insurance scenarios | Reproduce geographic joins, release-time availability, risk attribution, uncertainty intervals, scenario results, and source-rights protections; prohibit false parcel-level claims |

### 22.2 Performance service objectives, not current claims

Initial targets should be explicitly documented as **engineering goals** to validate or revise through benchmarks:

- High-frequency user interactions should usually provide visible feedback within ~100 ms on the reference test machine; slower backend work should be clearly asynchronous with status.
- Cached common company/profile views should target sub-second perceived load on a realistic covered universe, with cold-load metrics reported separately.
- Market chart operations should sustain responsive interaction with representative historical datasets, using viewport or sampling techniques where needed.
- Historical as-of queries and risk calculations have workload-specific targets established by measurement, not a universal one-size SLA.
- Dependency invalidation should inspect only affected edges and avoid global recomputation for small source changes.
- The CPU-only workflow must complete all core deterministic research tasks, even if large GPU workflows are slower or unavailable.
- Backtest accounting and reference pricing accuracy are release blockers. A fast wrong simulation is a failure.

### 22.3 Evaluation data discipline

Each benchmark publishes exact code revision, dataset provenance and legal status, time range, hardware, dependencies, warm/cold cache behavior, repetitions, measurement method, comparison baseline, known limitations, and output artifacts. Use both synthetic adversarial fixtures and legitimate real historical sources. Avoid selecting only favorable cases. **v1.1:** Include ICB-11 through ICB-18 in Section 32 for contract semantics, calibration, causal inference, robust decisions and portable domain packs. **v1.2:** ICB-19/20 are included in the flagship table above and governed by Section 33.

### 22.4 Additional version 2 benchmarks

The source benchmark suites ICB-01 through ICB-20 remain required. Version 2 adds ICB-21 through ICB-32 in Section 48 for model catalog coverage, nested composition, model tournaments, terminal accuracy, Quant Stack reconstruction, banking, private capital, household finance, institutional portfolio accounting, usability, plugins/rights and resilience. All new suites use the evidence, reproducibility and test-disclosure requirements already stated here.


---

## 23. Development roadmap, priorities, and release gates

The implementation roadmap is staged to build on the user-reported existing codebase. **Phases describe dependency order and accepted scope, not calendar promises.** No claim of completion is accepted without repository inspection and tests.

### Reported current baseline (November 2026)

| Phase | Agent-reported state | Important caution |
|---|---|---|
| Phase 1 | Implemented: SEC evidence, security identity, market bars, corporate actions, temporal kernel | Reported results not independently audited here |
| Phase 1.1 | Implemented: SEC historical archives, fact reconciliation, dependency index, time selection validation | Original XBRL-instance reconciliation and full market data remain limited |
| Phase 2 | Implemented: React terminal, financials, indicators, screens, watchlists, time machine, X-Ray, workspaces | Market bars remain synthetic in reported demonstration; coverage four issuers |
| Phase 2.1 | Agent reports implemented at `d0e4540`: IBM historical vendor prices, archived source manifests, research views, faster listing/screener, initial research objects | Only IBM has reported real prices; evidence-byte completeness and market-wide coverage remain limited; not independently audited here |
| Phase 3 | Agent reports second checkpoint `9b893ba3d36208061dc508c220d764589e2684b9`: typed IR, runtime, DCF/reverse DCF, Model Forge, application lifecycle | Reported 333 backend tests and 11 Studio checks; source bytes not fully archived, some historical reopen and browser coverage gaps, compile-scaling issue; not independently audited here |
| Phase 4 | Planned: Quant Lab, point-in-time features, strategy replay, research credibility | No actual Phase 4 implementation established in this spec |

### Phase 2.1: Research-ready terminal and contract freeze

- Audit reported Phase 1/2 tests against actual branch/revision.
- Import legally usable historical market data with source/adjustment/instrument metadata and verified reference cases.
- Expand beyond four issuers, benchmark screening and batch aggregate caching with dependency invalidation.
- Strengthen company accounting, peer comparisons, time-machine semantics and valuation cases.
- Define and test the initial Universal Research Object manifest and registry, without speculative implementation of all future engines.
- Introduce base data-rights records and open-source license/SBOM checks.
- Commit a reviewable and reproducible baseline, CI, representative fixtures and error budgets.

**Exit:** Real-data company workflow works with inspectable provenance; scalable issuer search and screener benchmarks; stable typed input/output and data rights contracts.

### Phase 3: Model Forge and Financial-Economic Compiler MVP

- Versioned `Dataset`, `Metric`, `Model`, `Experiment`, and `ResearchApplication` objects.
- Typed IR for fundamental financial arithmetic, periods, currencies, availability and scenario parameters.
- DCF, reverse DCF, selected statistical transformations, deterministic simulation and valuation cases.
- Model registry, provenance, dependency-aware incremental execution and cache correctness.
- Python SDK, initial visual graph editor, equation authoring, capability-limited custom operators.

**Exit:** One custom model produces matching code, equation and visual results; incorrect financial semantics are rejected; published ICB-01 and ICB-05 MVP passes.

### Phase 4: Quant Lab and trustworthy backtesting

**Event-program boundary:** Reserve and test *contract-schema* extension points for event/outcome/distribution/payoff definitions during Phase 4, but do not divert the quantitative-finance acceptance gates toward building a gambling product or a broad sports forecasting suite. The first optional read-only event-market research slice may begin after the core strategy/experiment accounting engine is verified.


- Point-in-time feature store, historical universe metadata, engine bake-off.
- Strategy registry, vectorized research, selected event-driven engine, simulation accounting and cost/benchmark assumptions.
- Statistical baselines, factor analytics, optimization, experiment ledger, walk-forward and model-selection audits.
- Financial Time Capsule and Research Credibility Report.

**Exit:** Reproducible end-to-end strategy experiment with documented biases/limits, correct order and portfolio accounting, credible out-of-sample evaluation.

### Phase 5: Institutional mathematics and multi-asset research

- Rates/curve and derivatives pricing adapter for QuantLib/ORE; instrument conventions, reference tests.
- Portfolio risk, factor exposure, stress tests, constrained optimization, credit modeling where data permits.
- Financial valuation and scenario models broadened across industries/assets.

**Exit:** ICB-02 published with independently reconciled pricing and risk cases.

### Phase 6: Atlas Learning Brain and scientific discovery

**Forecasting extension:** Add a proper-scoring-rule evaluation framework, rolling probability calibration, forecast versioning, and multi-model ensembles with leakage-resistant chronological tests. Domain-specific weather or event examples may be added only after baseline forecasting reproducibility and settlement taxonomy pass.


- Local or user-supplied AI providers, research planner with permission boundaries.
- Specialized ML pipelines and financial representation research with transparent baselines.
- Automated hypothesis/feature/model search, experiment memory, Model Auditor and negative-result registry.
- Optional AI-driven workspace/application authoring passing the same compiler checks.

**Exit:** Improved research productivity or predictive quality shown in named controlled evaluations; no mandatory LLM dependency.

### Phase 7: Global OSINT and economic world modeling

**Causal extension:** Expand source-backed relationship graphs into explicitly versioned causal hypotheses, structural scenarios, and uncertainty propagation. Any counterfactual must state identification assumptions and validation limitations, and must not automatically convert a news event into a prediction-market trade.


- Source registry for public records, government contracts, energy, geography and suitable event feeds.
- Temporal entity/economic graph, OSINT extraction audit and review states.
- Economic Reality Simulator, operating constraints, calibrated scenarios, portfolio connections.

**Exit:** ICB-04 and ICB-09 use source-verifiable economic relationships and explicit uncertainty. The Real Estate Investment Intelligence pack may begin its limited underwriting proof only after existing portfolio, credit/discounting, source-rights and spatial evidence contracts are stable. Do not block the core Phase 7 deliverable on acquiring proprietary property-level datasets.

### Phase 8: Application ecosystem and professional operations

**Execution extension:** Optional venue-specific action adapters, if ever implemented, require explicit user authorization, eligibility, anti-automation and licensing review, credentials isolation, audit logs, resource limits, order previews, kill-switches and paper-only tests. Keep them outside the core model runtime. No requirement to support actual event wagering is implied.


- Shareable versioned Research Applications, external plugin SDK, signing and rights packaging.
- Collaborative research, hosted compute/data, approved commercial sources, administration and secure workspaces.
- High-reliability monitoring, permissioned broker integrations only where justified and lawful.

**Exit:** Reproducible application publishing and rights-aware collaboration work across environments. Core mathematics remains open.

### The first public release

Ship a small number of **deeply verified** workflows rather than a 500-panel catalog. Preferred initial flagship: choose a company, inspect real evidence, build a custom valuation/forecast model, compare assumptions and baselines, test historical validity, produce an explainable conclusion, and save the research as a reusable application.

### Version 2 program expansion and migration policy

The original phase sequence above remains the recorded baseline. Section 48 adds cross-domain stages S0-S7 with release gates and profession-specific deliverables; it does not assert they are implemented. Section 46 defines a separate, optional **Quant Stack compatibility** migration based on the November 8 report. Never assume those four external tools are part of Atlas or that favorable backtests are independently verified. Any integration must preserve the original temporal/compiler/security contracts and default to research/paper-only execution.


---

## 24. Architecture decision record and contribution governance

Before a substantial implementation choice, create or update an ADR covering: problem, relevant workload, alternatives, licensing, correctness implications, benchmark or proof, decision, reversibility and maintenance cost. Examples:

- Python-first vs Rust/compiled-core split.
- SQLite vs PostgreSQL for collaborative state.
- DuckDB/Arrow/Polars/GPU backend selection.
- Backtesting engine choice and adapter semantics.
- Permissive core license and AGPL component strategy.
- Data-provider retention and historical snapshot policy.
- Model language versus ordinary Python adapters.
- Scope and cost limits for optional agentic research.

Code contribution policy: documented design principles; tests for new data semantics; reference validation for finance math; no fake demos; permission checks; dependency/license scans; public reproducible benchmark methodology; transparent limitation sections; changelog and migration notes.

---

## 25. Strategic risks and mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Licensed data access prevents full free Bloomberg-equivalent coverage | Permanent gap | Open computational core, rights-aware BYO feeds, public-source alternatives, explicit coverage charts |
| Too many integrated libraries create maintenance fragility | High | Pluggable adapters, controlled dependency count, contract tests, selective adoption |
| AI-generated features inflate superficial breadth | High | No feature is 'shipped' without real data, end-to-end tests, mathematical reference and source labels |
| Historical dataset incompleteness corrupts backtests | Critical | Time-aware evidence, delisted/universe checks, coverage flags, blocked false precision |
| ML model search overfits | Critical | Full experiment registry, untouched evaluation periods, multiple-testing diagnostics, baseline comparison |
| Financial or numerical bug causes misleading decisions | Critical | Independent math/accounting references, robust property tests, release-blocking discrepancies |
| Untrusted plugins or agent code compromise systems | Critical | Sandboxes, least-privilege permissions, no default broker access, signed packages and audit |
| License incompatibility or protected dataset redistribution | Critical | Data Rights Engine, SBOM, legal audit, rejection of incompatible code copying |
| GPU-only design excludes users | Medium | CPU-first reference behavior, optional acceleration and measured backend selection |
| Institutional scope delays a usable product | High | Flagship workflow gates, independently shippable components, explicit release thresholds |
| False claim of real-time news capability | High | Honest freshness/latency metrics, licensed feed option, no RSS polling equivalence claims |
| Complex UI undermines discoverability | High | Four spaces, progressive disclosure, contextual inspectors, keyboard UX, usability testing |
| Proprietary incumbent has network-effect moats | Structural | Compete on flexibility and scientific reproducibility rather than claiming total data/network parity |

---

## 26. Canonical end-to-end research demonstrations

### Demonstration A: Fundamental underwrite

Open an industrial issuer, ingest original filings and financial history, normalize statements, build operating assumptions and a three-statement model, estimate base/bear/bull fair values, compare against market expectations, inspect every source and equation, and save the thesis with monitoring triggers.

### Demonstration B: Custom ML earnings strategy

Select a documented security universe, construct publication-safe fundamentals and market features, train linear/boosted/neural baselines, preserve all trials, measure out-of-sample predictive quality, translate a candidate into a strategy, simulate costs and fills, and produce a Research Credibility Report. It is acceptable for the candidate to fail and for Atlas to say so.

### Demonstration C: Institutional rates model

Import authorized bond and curve inputs; build a reference discount curve with explicit conventions, price vanilla instruments, calculate DV01 and scenario risk, compare to a validated pricing library, expose sensitivities and input freshness, package as an editable interest-rate analysis app.

### Demonstration D: Geopolitical energy shock

Use source-backed infrastructure and energy information, map documented facilities and owners, specify transparent uncertain economic transmission channels, simulate operating outcomes, analyze cash-flow/credit effects, challenge causal assumptions, and display all limitations.

### Demonstration E: Invent a new research application

A user defines a new operating metric unavailable in the native catalog, writes a mathematical expression or compatible Python code, wires supporting observations, creates a chart and simulator, tests semantic validity, stores the model, adds an alert and exports the application. No bespoke hardcoded screen is required.

### Demonstration G: Property underwriting and geographic risk

Import an authorized example property and rent roll; construct dated leases, vacancy, expenses, taxes, insurance, replacement reserves, amortizing debt, and exit; independently reconcile unlevered and levered cash flows and scenarios. Join legally reusable FHFA/Census/HUD/FEMA context at the correct geographic aggregation. Clearly separate actual property comparables from regional statistical proxies and export an auditable acquisition memo.

### Demonstration F: Historical forensic replay

Reconstruct a company before and after a filing amendment and a revised macro release. Show what was provably public, what Atlas later ingested, and which previously published thesis/model outputs became stale. Replay a historical computation without leaking later facts.

---

## 27. Research source and software inventory

These are **evaluation candidates**, not automatically approved dependencies. Before use, verify current project state, source code license, model-weight license, data terms, security, maintainability, and compatibility. Commercial marks belong to their owners. As of November 2026, OpenBB stewardship is undergoing a transition toward OpenBQ; treat all upstream IDs and availability as subject to verification.

### Terminal, data, OSINT and usability

- [Bloomberg Professional](https://www.bloomberg.com/professional/) and [BQuant](https://www.bloomberg.com/professional/products/bloomberg-terminal/research/bquant/)
- [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) and [TradingView libraries comparison](https://www.tradingview.com/free-charting-libraries/)
- [OpenBB / OpenBQ repository](https://github.com/openbq-org/OpenBB) and [OpenBB organization](https://github.com/openbb-finance)
- [Neuberg](https://github.com/KoNananachan/Neuberg), review BSL terms before any reuse
- [Fincept Terminal](https://github.com/Fincept-Corporation/FinceptTerminal), AGPL and current project-specific notices
- [OpenTerminal](https://github.com/flavin/openterminal), MIT according to repository at research time; some data sources unofficial
- [World Monitor](https://github.com/koala73/worldmonitor), AGPL and separately controlled hosted data terms
- [OpenOSINT](https://github.com/OpenOSINT/OpenOSINT)
- [DeepDive OSINT](https://github.com/Sinndarkblade/deepdive), [DeepDive research](https://github.com/openintelligence-labs/deepdive)

### Core finance, quant and mathematical engines

- [QuantLib](https://github.com/lballabio/QuantLib)
- [Open Source Risk Engine](https://github.com/OpenSourceRisk/Engine)
- [OpenGamma Strata](https://github.com/OpenGamma/Strata)
- [QuantConnect LEAN](https://github.com/QuantConnect/Lean)
- [NautilusTrader](https://github.com/nautechsystems/nautilus_trader)
- [Qlib](https://github.com/microsoft/qlib)
- [RD-Agent](https://github.com/microsoft/RD-Agent)
- [ABIDES](https://github.com/abides-sim/abides)
- [PySR](https://github.com/MilesCranmer/PySR)
- [DoWhy](https://github.com/py-why/dowhy)
- [statsmodels](https://github.com/statsmodels/statsmodels)
- [arch](https://github.com/bashtage/arch)
- [CVXPY](https://github.com/cvxpy/cvxpy)
- [OR-Tools](https://github.com/google/or-tools)
- [Optuna](https://github.com/optuna/optuna)
- [Feast](https://github.com/feast-dev/feast)

### Event, probability and domain integration candidates (v1.1)

- [Kalshi API documentation](https://docs.kalshi.com/) and [Kalshi market settlement rules](https://help.kalshi.com/en/articles/13823822-market-rules), REST/WebSocket read-only evaluation subject to current agreement.
- [Polymarket public API documentation](https://docs.polymarket.com/), with venue and international/US product distinctions, CLOB data/market metadata and resolution rules.
- [PrizePicks current terms](https://www.prizepicks.com/help-center/terms-of-service), research/licensed-import consideration only; its restrictions against robot access mean it is **not an approved first-party scraping target**.
- [NOAA weather datasets](https://www.noaa.gov/) and [NWS weather products](https://www.weather.gov/), candidate external evidence for forecast-vintage/settlement experiments, subject to station and final-report differences.
- [SciPy](https://scipy.org/), [statsmodels](https://www.statsmodels.org/), [PyMC](https://www.pymc.io/), and [DoWhy](https://www.pywhy.org/dowhy/), statistical, probabilistic and causal baselines to evaluate rather than blindly import.

### Infrastructure, GPU and local models

- [Apache Arrow](https://arrow.apache.org/)
- [DuckDB](https://duckdb.org/)
- [Polars](https://pola.rs/)
- [NVIDIA RAPIDS](https://rapids.ai/)
- [PyTorch](https://pytorch.org/)
- [Triton](https://github.com/triton-lang/triton)
- [llama.cpp](https://github.com/ggml-org/llama.cpp)
- [Apache Iceberg](https://iceberg.apache.org/)
- [OpenLineage](https://openlineage.io/)

### Public data foundations

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [FRED API](https://fred.stlouisfed.org/docs/api/fred/) and [ALFRED](https://alfred.stlouisfed.org/)
- [GLEIF open LEI data](https://www.gleif.org/en/lei-data/access-and-use-lei-data)
- [OpenFIGI](https://www.openfigi.com/api/documentation)
- [U.S. Treasury interest rate feeds](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)
- [CFTC Commitments of Traders](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)
- [EIA API](https://www.eia.gov/opendata/)
- [FDIC BankFind](https://banks.data.fdic.gov/)
- [USAspending API](https://api.usaspending.gov/)
- [NOAA](https://www.noaa.gov/)
- [Copernicus Data Space](https://dataspace.copernicus.eu/)
- [USGS Landsat](https://www.usgs.gov/landsat-missions/landsat-data-access)
- [GDELT](https://www.gdeltproject.org/)
- [OpenAlex](https://openalex.org/)

---

## 28. Instructions for all future Atlas engineering agents

1. **Read this specification before planning major work.** Also inspect the codebase, latest contracts/ADRs, test results and source licenses. Do not assume agent-authored summaries match the actual working tree.
2. **Keep one canonical architecture.** New financial capabilities are extensions of shared objects, evidence, compiler, experiment and workspace contracts, not unrelated applications.
3. **Show implementation state honestly.** Mark `implemented_verified`, `implemented_unverified`, `partial`, `experimental`, `blocked`, and `vision_only` where appropriate. Code generation is not verification.
4. **Preserve financial meaning.** Every datum, derived metric, model and scenario has explicit units, time semantics, source/evidence or assumptions, version and coverage limits.
5. **Prefer reuse with proof.** Evaluate libraries, licenses, maintainability, test vectors, API isolation and integration costs. Do not import an entire repository because its feature list sounds impressive.
6. **Prototype along vertical slices.** Deliver working paths from raw source -> data quality -> financial model -> validated output -> UI -> reproducible artifact.
7. **Require independent tests and negative cases.** Include amendments, missing prices, delistings, bad calendars, mixed units, stale records, ambiguous matches, synthetic data and failing hypotheses.
8. **No artificial complexity.** Add Rust, GPU services, Kafka, graph databases or distributed orchestration only where measurable requirements justify them.
9. **No interface deception.** Every click, chart, data badge and claim must correspond to real behavior. Visibly label delayed, user-provided, simulated, estimated or unsupported results.
10. **Protect autonomy and rights.** AI cannot bypass data licensing, security checks or trade permissions. Private source data must not be shipped in public app exports.
11. **Do not abandon the open core.** Research mathematics, models, the compiler/runtime, and supported backtesting remain free and locally runnable. Monetize scarce licensed data, infrastructure and services, not artificially restricted algorithms.
12. **Benchmark against reality.** Publish complete methodology and accept negative results. If SQL is slower than Python or GPU slower than CPU, retain the faster correct backend for that workload.
13. **Do not expand UI clutter.** Every new capability should be contextualized within Explore, Studio, Lab or Monitor, with progressive controls and stable expert shortcuts.
14. **Integrate, do not drift.** Amend the master spec and changelog when a new feature materially changes architecture, release scope, data rights, scientific credibility or user workflows.
15. **Preserve engineering evidence.** Tests, CI, benchmark output, reproducible data fixtures, decision records, failures, and limitations belong in the repository, not only in chat logs.
16. **Event versus settlement.** Do not conflate underlying event truth with venue-contract payout or price movements. Parse the governing rules and preserve version history.
17. **Probability versus quote.** A 65-cent market price is not independently established 65% probability or a 65-cent executable fill. Use side-specific quotes, fees, liquidity and forecast calibration.
18. **Causal discipline.** A source-linked economic graph does not prove causal transmission. Identify estimands, assumptions, sensitivities and alternative explanations.
19. **Modular domain expansion.** Weather, sports, science, legal, venture and property functionality must arrive as optional validated packs, not as new unrelated products.
20. **Research before execution.** Any event-market integration defaults to read-only and paper-only; never rely on unauthorized scrapers or implicitly authorized trades.

---

## 29. Expansion decision and domain boundaries

### 29.1 Approved strategic expansion

Atlas remains **financial-first**, but its underlying substrate becomes **event-aware, probabilistic and decision-capable**. The shared technical architecture should support outcomes beyond financial assets when those outcomes can be grounded in lawful, versioned evidence. The expansion described in the supplied proposal is accepted as an architectural extension, not as a mandate to launch nine or twelve new applications at once.

**Retain:** the eight original Atlas systems, Explore/Studio/Lab/Monitor, Standard/Advanced views, Temporal Evidence Kernel, Financial-Economic Compiler, Model Forge, Quant Lab, Atlas Intelligence, Economic Reality Simulator, Research Operating System, and open-core philosophy.

**Add:** a universal event/outcome ontology, probabilistic forecasting and calibration, venue-specific contract and payoff semantics, a decision/problem representation, causal-hypothesis governance, and opt-in domain packs using existing infrastructure. Atlas may research Kalshi/Polymarket-type events through approved read-only connections. **Execution is neither a core dependency nor a default feature.**

### 29.2 Critique and deliberate exclusions

1. **Do not replace the mission with "intelligence about everything."** Universal subject coverage creates unpredictable data, legal, methodological and UI burdens. The core job remains financial/economic research and decisions; scientific, sports, weather, legal and geopolitical research are extensions with measurable reuse.
2. **Do not equate a listed exchange price with a true probability.** Spread, fees, adverse selection, inventory demand, resolution uncertainty and payout conventions separate tradable value from a probability forecast.
3. **Do not equate shared headlines with identical contracts.** Two markets can describe the same natural event while specifying different dates, authoritative sources, exceptions, appeal processes, or adjudicators.
4. **Do not call a logical mismatch risk-free arbitrage without proving identical state-contingent payoffs, feasible fills and transfer/settlement conditions.** Most cross-venue comparisons should be called `contract discrepancy` or `candidate opportunity`, not `arbitrage`.
5. **Do not turn causal intelligence into unsupported causal stories.** Economic source graphs establish links and observations; structural causal inference requires stronger assumptions or identification methods.
6. **Do not build a proprietary financial "world model" simply because a neural architecture sounds impressive.** Compare specialized statistical and probabilistic baselines first; use neural methods only if validated.
7. **Do not conflate exchange trading with fantasy contests or sportsbook bet slips.** They have different settlement, fee, entry, cancellation, and rights structures.
8. **Do not prioritize automated money-making workflows before core probability, historical simulation, compliance and experiment correctness.** A forecast is not an executable edge.
9. **Do not auto-route orders or autonomously place wagers.** Connected actions, if ever added, require independent authorization and suitability review; simulated and paper workflows remain valuable alone.
10. **Do not build proprietary-data dependence into free-core research.** Third-party data is an optional input, not a hidden subscription prerequisite to mathematical functionality.

### 29.3 The unifying product contract

A user should be able to ask: **"What precisely could happen, what information supports each outcome, what probabilities are defensible, what would the consequences be, and what decision remains justified after uncertainty and costs?"** Atlas must be able to answer each part separately, refuse unsupported leaps, and preserve the entire reasoning chain for replay.

The extension's architecture is `Evidence -> Event/Outcome -> Forecast/Distribution -> Contract/Payoff [optional] -> Scenario/Causal Model -> Decision/Experiment -> Audit/Monitor`. This is a *dataflow contract*, not a single monolithic model. Individual workflows may omit layers without fabricating them.

---

## 30. Universal Event and Probability Engine

### 30.1 Why a separate semantic layer is necessary

A company earnings release, weather threshold, sports statistic, election, regulatory announcement, bond default and binary event contract may all involve uncertainty, but they are not equivalent data types. Atlas needs reusable probability machinery with domain-specific evidence and settlement rules. It must support **binary, categorical, ordinal, continuous and jointly dependent outcomes**, without restricting every question to a YES/NO trading contract.

### 30.2 Core object definitions

| Object | Required information | Key distinction |
|---|---|---|
| `EventDefinition` | Natural-language question, version, entity and geography, observation/target window, data source, event identity | The underlying occurrence or measurement, independent of a market venue |
| `OutcomeSpace` | Exclusive and exhaustive outcomes where applicable, units, thresholds, boundary and missing-value rules | Outcomes must have clearly defined logic and compatibility |
| `ResolutionRule` | Authoritative source, cutoff/fixing time, source revisions, adjudicator, appeals, exceptions, authoritative rule-text hash, published/amended times | A settlement rule may not describe the same event as the intuitive headline |
| `VenueContract` | Venue and symbol/market ID, contract version, side, currency, fee schedule, lifecycle, settlement rule, payout structure, restrictions | Venue payoff semantics must not be merged by title |
| `MarketObservation` | Timestamped bid/ask, depth/trades when available, venue, size, validity, delay, provider timestamp and source rights | Observed prices are not model probabilities or assumed executable fills |
| `ForecastDistribution` | Target/conditional assumptions, issue and valid times, horizon, model/version, distribution or probability vector, uncertainty and baseline | A forecast is a research artifact, not a position recommendation |
| `SettlementObservation` | Final source result, determination, challenge state, actual payoff, provenance and finality timestamp | What the venue settles may differ from a researcher's event label |
| `PayoffFunction` | Outcome-to-cash-flow mapping, currency, side, collateral, fees, exceptional cases and settlement delay | Must be total over supported states or explicitly partial/unknown |
| `ProbabilitySnapshot` | Timestamped forecast distribution and calibrated interval, reference information set and model versions | Historical forecast replay requires original issuance snapshots |
| `PositionHypothesis` | Proposed side/size, intended decision time, quote reference, liquidity and cost assumptions | Not an order, not authorized execution |

Add schema evolution, content hashing, data rights, lineages, author and review states under Universal Research Objects. All contracts must preserve original rules text where license permits, plus parsed structure and the parser's evidence/uncertainty. Material rule amendments create new versions; settled contracts cannot silently rewrite old experiments.

### 30.3 Three forecasts that must never be confused

For underlying event `E`, research estimates `P(E | information_at_t)`. A venue-specific contract may instead require `P(venue_settles_YES | information_at_t, rules)`, including resolution ambiguity. Separately, price dynamics ask `P(executable_sell_price_at_t+h >= threshold | information_at_t)`. These are different targets. A model may be accurate on one and poor on another. A YES quote of 0.65 cannot become a 65% scientific conclusion by default.

Expected net payout also requires the actual state-contingent payoff distribution, acquisition side, executable ask/bid, fee schedule, time to settlement, financing, slippage, taxes if modeled, market access and residual risks. Report price and model probability alongside one another, never as interchangeable quantities.

### 30.4 Contract equivalence, logical consistency and hedging

Create a **Contract Semantics Verifier** with stages:

1. Compare ontology of the underlying event and measurement unit.
2. Parse and retain exact strike, inclusive/exclusive threshold, rounding, observation period and timezone.
3. Compare named settlement data source, preliminary/final vintages, adjudicator, exception, void/DNP, challenge and appeal clauses.
4. Form state-contingent payoff tables including nonbinary/void/partial states where present.
5. Declare `identical`, `conditionally_comparable`, `materially_different`, or `unresolved`, with a human-auditable explanation.
6. Only then compare executable prices and venue-specific fees, financing, settlement timing and liquidity.

Allow formal payoff-dominance or no-arbitrage checks on finite state spaces using exact rational or decimal arithmetic for financial values and numerical tolerances for probabilities. For continuous outcomes, discretization or analytical proofs must disclose approximation error. Apparent dominance does not constitute an executable opportunity if positions cannot be filled or legally held.

Example: two temperature contracts citing different stations, measurement windows, or final data sources are **not equivalent**, even if the headline city and day match. A price difference is therefore not necessarily a pricing error.

### 30.5 Probability model and uncertainty framework

Provide plug-in engines for Bernoulli and categorical forecasts, continuous distributions, hierarchical Bayesian estimates, calibrated classical models, regression, survival/hazard models, time series, joint/conditional outcome models, and eventually learned neural models. Specialized domain packs provide features and outcome definitions; the engine provides validation, distribution algebra and experiment tracking.

Required mathematical capabilities:

- Finite probability and normalization checks; explicit unknown/other outcomes and mutually exclusive/exhaustive category rules.
- Coherence constraints across nested thresholds, disjoint ranges and joint-versus-marginal forecasts.
- Dependence-aware scenario and portfolio sampling; never assume independent bets merely because they are separate market listings.
- Proper scoring rules: Brier and log loss for binary/categorical targets; CRPS and quantile/coverage diagnostics for continuous variables.
- Reliability diagrams, calibration by subgroup/time horizon and observed sample size; confidence and credible intervals where justified.
- Discrimination, sharpness, baseline skill, distribution shift, regime degradation, class imbalance and selectively missing labels.
- Rolling-origin, as-issued forecast snapshots and embargoed evaluations where overlapping labels cause leakage.
- Forecast fusion with explicit correlation of model errors; naive averaging does not guarantee diversification.
- Decision-specific loss functions and base-rate uncertainty, separate from pure statistical accuracy.

Do not treat a visually smooth calibration plot over a small sample as strong validation. Record all attempted model configurations and benchmarks. Retain abstention/insufficient-evidence as a valid forecast state.

### 30.6 Market data, historical replay and information clocks

Read-only adapter candidates include [Kalshi API](https://docs.kalshi.com/) and [Polymarket developer documentation](https://docs.polymarket.com/). Each adapter must follow the current provider agreement, rates, authentication, rate limits, geography and commercial-data rules. SDK presence alone does not grant unrestricted redistribution or account access.

Persist: market listing/creation time; contract and settlement-rule versions; quote/trade exchange time and receipt time; raw snapshot hash; provider and entitlement metadata; close/determination/payout times; and corrections. Historical data may expose trades or candles without reconstructable historical order books. Mark corresponding simulations as having **unobserved depth**. API refresh frequency is not guaranteed latency; the UI must display actual freshness.

The Time Machine must reconstruct the forecast, contract rule and observable market data available on the original decision date. Later rule amendments, revised official observations, final settlement results, current order books, and later-written scientific reports must not leak into historical feature sets.

### 30.7 Phase-gated reference implementation

Begin with a **read-only, paper-only event laboratory** after Quant Lab's accounting and experiment foundations are working. Use one narrow category, such as authorized public weather events, where target measurements and settlement sources can be compared to independently archived official observations. The initial deliverable should implement:

- A verified `EventDefinition` and venue-specific `Contract` parser with snapshots.
- A properly dated public observation pipeline, a deliberately simple baseline forecast, and a calibration evaluator.
- One historical simulation using known order/quote availability limitations and conservative fee/liquidity assumptions.
- A contract-comparison UI demonstrating why similar headlines can have different payoffs.
- A reproducible research app with Brier/log scoring, payout/market price separation and audit trace.

**Not in the first slice:** sports contest ingestion from prohibited channels, live exchange trading, automated real-money orders, production market-making, large-scale agent trading, or claims of free riskless arbitrage.

---

## 31. Causal, decision, and opportunity intelligence

### 31.1 Causal graph with identified claim status

Atlas's Economic Intelligence Graph should support *three different kinds* of relationship:

- `ObservedRelation`: an evidenced association, corporate relationship, ownership, location, contract or measured correlation.
- `MechanismHypothesis`: a proposed pathway such as energy cost -> margins -> cash flow, with sign, scope, uncertainty and refutable assumptions.
- `CausalEstimate`: a precisely specified estimand with identification strategy, control set, assumptions, validation, uncertainty, study population and sensitivity results.

A source-backed corporate supplier link is not evidence that a specific supply shock will lower earnings by a quantified percentage. A neural network's feature importance is not a causal effect. Causal graphs must have review/version states, uncertain edge labels and alternative explanations. Include refutation and sensitivity tools using established statistical packages where applicable.

### 31.2 Cross-domain causal event research

Canonical example: regional energy demand shock.

`Weather forecast vintage -> electricity load distribution -> regional generation/capacity constraints -> utility/industrial input exposure -> company operating-cost scenario -> cash-flow/credit/valuation model -> portfolio risk -> optionally comparable public event contracts.`

For each arrow, Atlas must disclose whether the relationship is observed, directly measured, statistically estimated, mechanically defined, or purely hypothetical. Where exact contracts, operating exposure or quantity data are unavailable, present ranges and scenarios, not invented precision. An event-market price may be a comparison signal, not necessarily independent evidence or ground truth.

### 31.3 Decision Problem Engine

Add versioned `DecisionProblem`, `Action`, `State`, `Payoff`, `Constraint`, and `DecisionPolicy` objects. The engine should ask:

- What is the objective: maximize expected financial value, minimize expected loss, satisfy a risk budget, acquire information, or improve forecast quality?
- What actions are available and authorized? Doing nothing must be included.
- What states of the world and settlement states matter? What probability models or credal bounds support them?
- What are the units, time horizon, risk preferences, capital/liquidity/resource constraints, and reversibility?
- What are the costs, opportunity costs, transaction constraints, tail losses, and model uncertainty?
- How sensitive is the recommendation to forecast assumptions, missing data, costs and regime shift?

Provide expectation and risk measures, scenario dominance, robust/minimax sensitivity, and optional utility/constraint optimization. Avoid presenting one model's expected-profit ranking as a globally optimal action. `Recommendation` is an explanation and reversible proposal, not a command to trade.

### 31.4 Opportunity Engine as comparative research, not a profit bot

Use a structured pipeline:

`Forecast / Structural Valuation -> Venue Contract / Financial Asset -> Executable Quote Snapshot -> State-contingent Payoffs -> Fees and Liquidity -> Model and Resolution Risk -> Counterfactual Stress -> Auditable Candidate`.

Rank candidate discrepancies by *net modeled edge, uncertainty, time horizon, accessible capital, execution feasibility, concentration, information freshness and worst-case loss*. Provide independent baseline comparisons and plausible alternate probabilities. If sign or ranking reverses under modest assumptions, flag fragility rather than an attractive score. **No positive edge or money-making opportunity is guaranteed.**

### 31.5 Value of information and research allocation

One addition beyond the supplied proposal is **Value of Information (VOI)**: quantify whether conducting another experiment, obtaining a better data source, waiting for a release, or testing an assumption is expected to change a decision enough to justify its cost.

Support expected value of perfect information (EVPI), expected value of sample information (EVSI) where estimable, and bounded sensitivity/probe selection. Since VOI depends on current beliefs, state, action set and loss function, store all as versioned research artifacts and do not overstate precision. This makes Atlas not just a model inventor but a resource allocator for scientific and investment research.

### 31.6 Multi-agent research without unaccountable autonomy

Independent agents may propose competing hypotheses, retrieve evidence, challenge methods, run approved experiments and audit the final claims. Every agent must operate on typed objects with immutable experiment logs, budgets, tool permissions, source access control and reproducible prompts/models where available. A distinct adversarial reviewer must be able to challenge causal assumptions, settlement rules, data leakage and model-selection bias. Substantive conclusions require deterministic or evidence-backed artifacts; multiple agents agreeing is not itself verification.

### 31.7 Legal, ethical and action boundaries

When research involves legal cases, executives, individual consumers, athletes or politically sensitive predictions, protect personal information and distinguish public allegations, formal findings and statistical indicators. Do not infer wrongdoing from network connections or model anomaly scores. Venue access, eligibility, age requirements, jurisdiction, commercial data, market abuse and account authorization are separate compliance checks. No bypasses; no silent placing of bets or trades; no compulsory payment accounts for core research.

---

## 32. Domain packs, implementation gates, and event benchmarks

### 32.1 Cross-domain packages within the original eight systems

The proposed twelve domains can be reduced to **six optional packs** using the same Atlas substrate. None needs a new permanent navigation tab.

| Pack | Scope and financial relevance | Data/method boundary | Priority |
|---|---|---|---|
| **Event & Forecast Intelligence** | Economic releases, weather, Kalshi/Polymarket research, outcome probabilities, contract semantics | Read-only licensed/public APIs; no default execution | First experimental extension after Quant Lab core |
| **Investment & Transaction Diligence** | Company/startup/fund/acquisition/counterparty, legal/regulatory and forensic accounting | Evidence-linked findings; confidential third-party material requires rights and access controls | Core financial research extension |
| **Economic & Geopolitical OSINT** | Trade, logistics, energy, sanctions, public procurement, infrastructure, public relationships | Maintain observed/inferred causal separation and data freshness | Existing Phase 7 track |
| **Scientific & Technical Intelligence** | Papers, patents, open benchmarks, technical readiness and commercial implications | Reproducibility, scientific uncertainty, rights for full text and datasets | Later research pack |
| **Real Assets & Infrastructure** | Residential/commercial real estate underwriting, leases and debt, REITs, infrastructure, construction, climate and energy exposure | Property-level data rights, location privacy, geographic uncertainty and comparable-sales provenance; see Section 33 | Next sector vertical after essential financial/OSINT foundations |
| **Sports & Consumer Forecasting** | Weather/sports statistics as model research, consumer trends and public aggregate signals | Sports lineups and fantasy payoffs require special contracts, lawful data access and eligibility | Deferred; no initial scraping |

Cross-cutting features including fraud forensics, venture intelligence, network intelligence, regulatory tracking and persistent research agents fit within these packs and existing Atlas systems. A pack is a **dataset + ontology extension + models + validated benchmark + UI composition**, not a copied product or an entirely new backend.

### 32.2 Developer package manifest and gate

A pack must declare supported object/schema versions; required sources and redistribution permissions; time and revision semantics; model and operator dependencies; privacy sensitivity; coverage claims; evaluation data; baseline methods; independent reference cases; performance budget; and allowed actions. It must install/remove cleanly without altering core financial values or requiring an LLM. Pack outputs remain reproducible using the same Research Application and Time Capsule contracts, or must state why not.

Never add domain-specific exceptions directly into the Financial-Economic Compiler when they can be expressed as a registered typed operator, source adapter, domain schema or execution plugin. Do not create one-off financial identities for contracts or one-off UI navigation trees.

### 32.3 Stage gates and development order

**E0 (Phase 4 foundation):** Stabilize strategies, point-in-time features, event-clock interfaces, experimentation, accounting and full replay. Define minimal event/outcome/contract/distribution schema contracts, but protect current Phase 4 delivery scope.

**E1 (post-Phase 4 optional vertical slice):** One venue's permitted read-only market metadata and quote history; parse and version settlement terms; reproduce snapshots. Publish an API/license and source-quality audit.

**E2 (probability laboratory):** A reference weather or macro event family, archived as-issued forecasts, calibrated baselines, proper scoring, outcome-space checks, and first cross-venue comparison only after settlement equivalence proof.

**E3 (after institutional/statistical foundation):** Joint and conditional outcome modeling, scenario uncertainty, portfolio exposure and formal decision analysis. Integrate ORE/QuantLib or optimization engines only where appropriate.

**E4 (with Phase 7 OSINT graph):** Multi-hop economic event hypotheses, identification diagnostics, causal sensitivity and financial impact reconciliation.

**E5 (optional, governance-gated):** No requirement to implement. Any account-connected or authorized execution adapter is an independent security/compliance project and must not be a prerequisite for earlier research releases.

This order makes Phase 4's strategy ledger and time-safe research useful for event markets without prematurely shifting engineering away from the institutional-finance core.

### 32.4 New public Institutional Capability Benchmarks

Add the following suites to the Atlas ICB. Passing requires independent fixture generation, counterexamples and a methodology report.

| ID | Benchmark | Non-negotiable checks |
|---|---|---|
| **ICB-11 Event Semantics** | Parse two same-headline contracts with different settlement rules | Preserve rule-text hash, source, time, adjudicator, exceptions and unequal payoff states; reject false equivalence |
| **ICB-12 Calibration and Forecast Replay** | Issue forecasts before outcomes and grade after settlement | Brier/log/CRPS as appropriate, reliability plots, base-rate and chronological benchmarks, as-issued vintage isolation |
| **ICB-13 Market Feasibility** | Compare simulated payoff and market quotes | Separate YES/NO bid/ask, fees, depth, order timing, liquidity, price and resolution uncertainty; no implied executable fill from mids |
| **ICB-14 Causal Research** | Model economic shock -> company financial outcome | Explicit estimand, assumptions, source/hypothesis labels, controls/sensitivity and null-result reporting |
| **ICB-15 Decision Robustness** | Solve a scenario-dependent research/investment choice | Do-nothing baseline, payoff/cost accounting, uncertainty and constraints; demonstrate reversal or abstention under adverse assumptions |
| **ICB-16 Domain-Pack Portability** | Install a non-equity pack and create a research app | Uses original UROS/FEC/Time Capsule/SDK; no core schema fork, no unsanctioned new data rights |
| **ICB-17 Evidence Conflict and Monitoring** | Inject contradictory reports and revised settlement/outcome records | Mark conflicts, preserve old versions, invalidate only dependent results, explain downstream consequence |
| **ICB-18 Value-of-Information Audit** | Decide whether to buy data or run another experiment | Reproduce VOI under explicit decision losses and sample assumptions; compare with doing nothing and known analytical cases |

A low-latency event feed is not a success criterion unless actual source timestamps and end-to-end latency are measured. The goal is verifiable research quality before real-time competition.

### 32.5 Institutional replacement definition, revised

Success should be evaluated at the **complete workflow** level: financial underwrite, custom model development, statistical forecasting, pricing/risk, historical simulation, evidence-linked diligence, and event/decision reasoning. Atlas can reasonably aim to replace paid *software functionality* for specific workflows even when proprietary analyst consensus, live market depth, private communication, or commercial news remains unavailable. Publish validated parity/advantages/limitations per workflow. Do not market blanket Bloomberg equivalence based on UI resemblance or unverified feature counts.

### 32.6 New integrated flagship demonstration: Event to balance sheet

Demonstrate a historically valid, end-to-end research application:

1. Retrieve archived weather forecasts issued before a specified date and identify the exact contract's official settlement station, observation window, and rule version.
2. Construct a calibrated probability distribution for the defined event; compare with a simple seasonal/historical baseline and venue-specific executable quotes if available.
3. Independently map the weather/energy event into a constrained energy-cost scenario for a documented public company, with estimated exposure ranges and alternative explanations.
4. Recalculate forecast operating expenses, FCFF, valuation and credit sensitivities through the existing Financial-Economic Compiler.
5. In Quant Lab, compare historical model versions and benchmark research performance with proper scoring and accounting. Explicitly disclose unavailable data and uncertain causal links.
6. Present the forecast, contract-resolution risk, business scenario, uncertainty, financial result, optional paper-only trade comparison, and source provenance as one saved Research Application.
7. Use Time Capsule to reconstruct the original information set and Sentinel to explain which new evidence would invalidate which outputs.

**Passing this demonstration is more meaningful than launching hundreds of disconnected event, sports, or OSINT dashboards.**

### 32.7 Further technical questions to research before implementation

- Which venues allow archival, commercial reuse, and derived redistribution of exact rule text, quotes, trades, and order books?
- Are enough **historical contract rule versions** and authoritative settlement records available for an honest as-of benchmark?
- Which weather forecasting archives contain actual issuance-time runs rather than reconstructed or revised datasets?
- Can venue resolution edge cases be modeled as a complete payout state machine rather than a YES/NO shortcut?
- Which probability forecasts are more stable than calendar/seasonal and naive market baselines across regimes?
- How can graph nodes represent observed causal mechanisms and explicit uncertainty while supporting incrementally recomputed financial consequences?
- What combination of schema/compiler extensions preserves strong typing without causing Phase 3's large-graph compile performance to regress?
- What downstream actions, if any, are appropriate to automate without risking legal, financial, or privacy harm?

The answers must be supported by dated provider documentation and independent test artifacts, not inferred from project marketing.

---

## 33. Atlas Real Estate Investment Intelligence

### 33.1 Scope and strategic thesis

**Atlas Real Estate Intelligence** is the first substantial implementation of the **Real Assets & Infrastructure** domain pack introduced in Section 32. Its purpose is to let individual and professional researchers underwrite, compare, stress, monitor and explain property investments using the same financial mathematics, credit/risk system, historical evidence, optional AI and Research Application infrastructure as public securities.

This is **not** a ninth standalone product, a replacement for broker-specific MLS access, an automatic appraisal or property inspection, or a plan to recreate CoStar/ARGUS proprietary datasets for free. Atlas should aspire to equal or exceed the *transparency, modeling flexibility, reproducibility and integration* of selected real-estate workflows, while truthfully disclosing data and market-coverage deficits. Study ARGUS Enterprise's lease-by-lease modeling, DCF/capitalization, valuation sensitivity, debt and asset management as functional benchmarks, but do not copy proprietary interfaces or algorithms wholesale.

**Asset families and their distinct levels of support:**

| Family | Required research workflows | Initial scope |
|---|---|---|
| Residential rental | Single-family, duplex/small multifamily, rental versus acquisition, financing and maintenance | First vertical slice; user-supplied property data acceptable |
| Multifamily | Units, turnover, lease concessions, vacancy, renovation, market rent, operating expenses, debt | First lease-aware extension after single-property proof |
| Commercial property | Office, retail, industrial, hospitality and mixed-use with complex leases, rent steps and tenant improvement allowances | Incremental; specific contract conventions must be explicitly supported |
| Development and value-add | Land, entitlement, construction draws, absorption, lease-up, interest carry, stabilization and exit | Scenario-first later phase; do not present as built initially |
| REITs and listed real estate | Public-company financials, FFO/AFFO, leverage, NAV, asset exposure and equity valuation | Reuse core SEC, fundamentals and listed-security services |
| Real estate credit / CMBS | Mortgage amortization, floating rates, DSCR, covenants, defaults, recovery, tranche scenarios | Simple loans first; securitization waterfall only with tested contract terms and appropriate data |
| Investment entities and partnerships | Ownership splits, fees, preferred returns, promote/participation and investor-level returns | Future waterfall component with independent reference scenarios |

**The differentiation:** A property is not merely a ticker, address or valuation number. It is a **versioned, geolocated operating asset** with physical characteristics, contracts, counterparties, expenses, claims, financing, climate/environmental exposures and partially observed operating data. Every reported return must resolve to explicit lease, operating, financing, sale and investor-distribution assumptions.

### 33.2 First-class objects and ontology extensions

Extend the Universal Research Object System with typed domain objects, referenced rather than duplicated:

- `RealProperty`: durable local asset ID, address/location fields separated from public-display permissions, optional parcel/building identifiers, jurisdiction, asset type, geography, size, units, construction vintage and geocoding quality.
- `Building` / `Unit` / `Space`: occupancy, leasable area, usage type, efficiency measures, physical dependencies and documented condition.
- `Lease`: effective date, expiration, rent schedule, currency, escalation convention, concessions, tenant costs, reimbursement rules, extensions/options and evidentiary status.
- `Tenant` / `Counterparty`: scoped identity, privacy/permission policy and evidence-backed tenant concentration; no unrestricted personal data publishing.
- `OperatingStatement`: property-level income and expense categories with fiscal period, source and audit status.
- `CapitalProject`: renovation/development budget, timing, contractor assumptions, draws, contingencies and completion constraints.
- `PropertyLoan`: lender and collateral reference, principal, amortization, rates, resets, term, maturity, covenants, reserves, recourse and fees.
- `MarketComparable`: arm's-length or other transaction/listing status, observed date, source, geographic fit, property attributes, adjustment notes, inclusion criteria and rights.
- `PropertyValuation` / `UnderwritingCase`: dated asset snapshot, financial model, cap-rate and discounting conventions, source assumptions, uncertainty and sensitivity.
- `PropertyPortfolio`, `InvestmentVehicle`, `InvestorWaterfall`: asset positions, debt, investors, ownership, fees, distributions and investor-level reporting.
- `SpatialExposure`: hazard and infrastructure layer, source vintage, resolution, coordinate reference system, intersection method, property geometry confidence and exposure uncertainty.

Link properties to the existing `Entity`, `Asset`, `Instrument`, `Evidence`, `Location`, `Event`, `Model`, `Forecast`, `Scenario`, `DecisionProblem` and `ResearchApplication` families. Company ownership of a building does not imply ownership of every parcel within a facility footprint. Geocoded proximity is not itself a causal exposure or legal encumbrance.

**Type/period rules:** currency and date conventions, rentable versus gross square footage, monthly versus annual payments, nominal versus inflation-adjusted amounts, contract versus market rent, historical versus forecast occupancy, before/after-tax returns, property versus equity cash flows, and cash versus noncash costs must remain distinct. Preserve fiscal period alignment and tax jurisdiction assumptions. All property/loan calculations must share FEC operators and independent tests rather than being computed only in UI widgets.

### 33.3 Core valuation, credit, and asset-management mathematics

Implement the following with documented signs, time conventions and robust edge-case tests:

1. **Rent roll and effective income:** gross potential rent, vacancy/credit loss, concessions, ancillary income, reimbursement income, percentage rent where supported; lease-by-lease and monthly accrual/cash-flow views.
2. **Net operating income (NOI):** effective gross income minus the explicitly modeled property operating expenses. Financing expenses, income tax, depreciation and capital expenditures must not be silently counted as NOI operating expenses.
3. **Capital expenditures and free cash flow:** recurring replacement reserves, renovations, tenant improvements and leasing commissions separately from NOI; distinguish reserves from actual cash spend and avoid double-counting.
4. **Asset valuation:** direct capitalization (`NOI / cap rate` under a dated, stabilized and explicitly defined NOI assumption), multi-period unlevered DCF, discounted reversion, transaction/sale costs and sensitivity to discount/terminal cap rates.
5. **Loan schedules:** fixed/floating rates, payment timing, amortization, interest-only phases, points/fees, refinance, balloon/maturity, DSCR, debt yield, LTV, repayment and interest-rate stress. Reject undefined conventions or impossible repayment schedules.
6. **Investor cash flow:** levered annual/monthly equity flows, reserves, acquisition and disposition costs, cash-on-cash return, unlevered and levered IRR/XIRR, NPV, equity multiple, hold period and time-weighted/money-weighted distinctions.
7. **Commercial tenancy:** reimbursements, expense stops, percentage rent, rent-free periods, options, downtime, vacancy costs, leasing commissions, TI allowances and tenant concentration in later modules.
8. **Development:** land/entitlement, costs and contingency, draw schedules, interest capitalization, lease-up, stabilization, exit and time/cost overrun scenarios. Forecast outputs remain hypothetical, not assured project values.
9. **REIT and public real estate:** SEC-sourced FFO/AFFO-like reconciliations with issuer-specific definitions; NAV, leverage, maturities, interest coverage and portfolio/sector exposure. Avoid blindly comparing nonstandard adjusted metrics across issuers.
10. **Investment waterfalls:** preferred returns and catch-up/promote mechanics only where the exact legal allocation rules, reinvestment, capital-return priority, fees, crystallization, and multiple-hurdle conventions are modeled and verified.

The standard report must distinguish **gross property yield, unlevered asset performance, levered equity returns, modeled terminal value, contractual payment obligations, and uncertain resale proceeds**. No app may silently optimize an acquisition on a single modeled IRR without showing terminal-price dependence and downside loss scenarios.

### 33.4 Market intelligence, geospatial evidence and free data

Prioritize legally reusable, attributable US data, plus user-imported authorized property records. The sources below are candidates, **not** guaranteed commercial redistribution grants or parcel-level sources:

| Source | Useful coverage | Important limitation |
|---|---|---|
| [FHFA HPI](https://www.fhfa.gov/data/hpi/datasets) | Repeat-sales home-price indexes across national, regional and some subregional geographies | Regional index change is not an individual home's value or comparable sale; publication/revision dates must be tracked |
| [Zillow Research downloadable datasets](https://www.zillow.com/research/data/) | Home value and rent indexes, inventories and selected regional indicators | Attribution and applicable terms; modeled regional values are not property-level lease comps |
| [HUD FMR and Small Area FMR](https://www.huduser.gov/portal/datasets/fmr.html) | Program rent standards by geography and bedroom count | A government payment benchmark, not proof of achievable market rent for a given unit |
| [Census ACS](https://www.census.gov/data/developers/data-sets.html) | Population, income, housing stock, household and commuting variables | Sample/error and geographical limitations, publication lags, API-key requirements where applicable |
| [Census Building Permits Survey](https://www.census.gov/construction/bps/index.html) | Local new residential permit activity and construction pipeline proxy | Permits do not equal completions or local market supply delivered |
| [FEMA National Risk Index](https://www.fema.gov/flood-maps/products-tools/national-risk-index) | County/tract-scale hazard-risk context | Index is not a site-specific insured loss estimate or substitute for property-specific flood information |
| [HMDA public mortgage data](https://ffiec.cfpb.gov/) | Mortgage origination/denial and lending-market aggregate research | Consumer privacy, variable and release limits; not comprehensive property mortgage ledgers |
| [DOE Building Performance Database](https://www.energy.gov/cmei/buildings/building-performance-database-bpd) | Building operational and energy-efficiency peer characteristics | Anonymized, aggregated access; not verified physical energy consumption for a selected building |
| Local assessor, recorder, zoning and permitting portals | Parcels, assessments, deeds, tax history, local land-use details where published | Uneven local availability, varying accuracy, rights, fees and historical coverage |
| Authorized user documents | Rent rolls, T-12 financials, offering memoranda, inspections, loan sheets, tax bills | Often confidential, biased or incomplete; never redistribute without permission |

Design a **Real Estate Source Rights Gateway** to enforce data entitlements, location/tenant privacy, citation, allowed retention, model-training restrictions, and export/redistribution limitations. An accessible web page is not automatically an authorized bulk API. Do not scrape MLS, paywalled broker platforms, CoStar or proprietary listings to manufacture a free nationwide property transaction database.

Use explicit geographies and join semantics: parcel geometry when available; otherwise centroid/buffer, census block group/tract, county, metro or ZIP with declared precision. Avoid ecological inference such as treating tract median rent, county appreciation, or mapped hazard as an individual property's observed rent, return or damage probability. Snapshot data releases; corrected hazard layers or revised ZIP definitions can alter historical conclusions.

### 33.5 Atlas Property Twin and counterfactual research

A flagship advanced capability should be an **economic property twin**, not a photorealistic building reconstruction. It is a structured digital model of the asset's operations, financing, location and uncertainty.

Example chain:

`Historical rent roll + observed financing + regional supply and demand + weather/insurance hazard evidence + tax and energy assumptions -> vacancy/lease-up/expense/debt scenarios -> NOI and free cash flow -> property valuation and equity outcomes -> portfolio risk -> research decision`.

The twin should support independent perturbations to rent, occupancy, maintenance, insurance premiums, property taxes, cap rates, interest rates, construction delays and regulatory changes. Distinguish directly observed exposures from inferred transmission paths. Show ranges, confidence/identification limits, and whether a projection relies on sparse property data. Research Sentinel may monitor new permitted evidence such as permit activity, rate changes or regional rent indexes and invalidate affected scenarios; it must not automatically make or finance a purchase.

Cross-domain reuse:

- **Fixed income:** property mortgages, floating-rate funding, hedging and refinance risk.
- **Quant Lab:** long-horizon, sparse/illiquid transaction series with irregular valuation observations and appraisal-smoothing concerns, not fictitious daily mark-to-market prices.
- **Event and Forecast:** probability of vacancy, completion delay or threshold breach with explicit outcome deadlines, labels and calibration.
- **Portfolio Lab:** liquidity-constrained, highly concentrated, geographically correlated real-assets exposure.
- **Economic OSINT:** zoning, transport, utilities, employer relocation and localized supply shocks, with source-backed causal-status labels.
- **Model Forge:** tenant-level discounted cash flows, debt waterfalls, alternative expense models, demand models and custom property types.

### 33.6 Special risks and strict correctness boundaries

- **Illiquidity:** real estate returns are irregularly observed, transaction costs high, sales uncertain and property-specific. Do not compare smoothed appraisal returns directly with daily traded-stock volatility without correction and caveats.
- **Leverage:** cap rate is not mortgage interest rate; DSCR, LTV, refinance and floating-rate resets can dominate modeled equity outcomes. Stress covenant breaches and inability to refinance.
- **Location specificity:** a local index or rent estimate does not prove a particular property's price, rent, taxes, insurance availability, occupancy or permissible use. Validate official parcel/title/zoning records and professional inspections externally when required.
- **Market comps:** listing ask price, recorded transaction, assessed value, modeled estimate and broker opinion are different classes of observation. Every comparable must be labeled with transaction status, adjustments, date, source and selection bias.
- **Tax/legal:** property taxes, depreciation, capital gains, partnerships, zoning, title and fair-housing/legal requirements vary by jurisdiction. Model declared rules and uncertainty; do not advertise a universal tax/legal opinion engine.
- **Privacy and fairness:** sensitive property-owner and individual tenant records require access controls and lawful use. Avoid unjustified neighborhood risk scores based on protected traits, and avoid targeting/exclusion recommendations inconsistent with fair housing obligations.
- **Insurance and climate:** FEMA tract-level risk and flood zones are not substitutes for an actual quote, engineering inspection, lender requirement or parcel-specific assessment.
- **Data vintage:** current public real estate datasets and assessments may be revised; dates of transaction, recordation, release, Atlas ingestion and model availability must remain distinct.

### 33.7 Implementation and benchmarks

**RE0, contracts and data audit (after Phase 5/6 fundamentals):** Define property, lease, loan, operating statement, market comparable, geospatial exposure and source-rights schemas. Build a public-source registry and sample legal user-import process. No proprietary data dependencies or parallel computation stack.

**RE1, initial public underwriting slice:** Implement a user-input single residential rental / small multifamily asset with cash-flow model, amortizing loan, closing/sale costs, vacancy, maintenance and sensitivity. Verify hand-calculated accounting. Combine with FHFA/Census/HUD regional context labeled strictly as context, not property comps.

**RE2, lease and portfolio layer:** Lease-by-lease modeling, rent-roll import and reconciliation, IRR/DSCR, multi-property portfolio, debt stack, reserves, shareable versioned Research Applications, and Real Estate X-Ray. Where supported, ingest county parcel/source evidence and authenticate GIS joins.

**RE3, professional real-estate research:** Commercial lease terms, redevelopment and construction schedules, property-level risk maps, optional confidential data-room import, portfolio financing, REIT asset exposure and selected investor waterfalls. Require independent tests and access control before private material is shared.

**RE4, advanced probabilistic/economic research:** Estimated rent/occupancy distributions, lender refinance stress, geographically correlated climate and demand scenarios, monitored property twins, automated underwriting challengers and robust investment decision comparison. Do not promote probabilistic forecasts before proper out-of-sample regional and time-vintage evaluation.

**ICB-19:** The same lease-and-loan model through the FEC, Python SDK and UI must reconcile NOI, cash flows, debt schedule, DSCR, sale proceeds, equity IRR and NPV with independent math and a saved/replayed application. Include edge cases: vacant building, negative NOI, missing rent, floating-rate reset, prepaid loan, multiple sale dates and negative equity.

**ICB-20:** Reproduce a property risk analysis using dated, attributable housing/geography/hazard data, document resolution and missingness, quantify scenario sensitivity and audit a false-precision attempt (for example, county rent labeled as a verified tenant rent). An external user should be able to inspect and challenge the entire calculation chain.

**Minimum flagship app:** Import a legally acquired property fact sheet and rent roll, set financing and operating assumptions, inspect a month-by-month underwriting model, stress vacancy/insurance/rates/cap rate, compare alternatives, reproduce historical evidence, and export an auditable investment memo. A report containing only a Zestimate-style predicted price is *not* sufficient.

**Product priority:** The first real estate vertical slice should follow stable financial valuation, portfolio/risk, data-rights and temporal/geospatial interfaces. It can be implemented as an independent domain-pack contribution without delaying core Quant Lab, Learning Brain, or OSINT milestones. Do not start a nationwide commercial-comps ingestion program before these release gates are met.

---

---

## 34. Platform constitution: the universal financial operating system

### 34.1 North-star product contract

Atlas is intended to be the **open financial operating system** for researching, understanding, modeling, evaluating, and managing financial decisions. It must be useful to a new investor with no coding knowledge and to specialists working in quantitative research, discretionary trading, equity and credit research, fixed income, portfolio management, investment banking, venture capital, private equity, real estate and personal financial planning. **One evidence foundation, one model substrate, one application platform; multiple user experiences.**

The objective is workflow substitution, not ungrounded claims that Atlas will immediately surpass Bloomberg, LSEG, Capital IQ, Aladdin, FactSet, PitchBook, Carta, TradingView, thinkorswim, professional OMS/EMS products, spreadsheets, accounting tools, or consumer financial apps. Proprietary feeds, private datasets, trusted collaboration networks, regulated activities, custody and exchange connectivity are not reproduced by code alone.

Every proposition in this document has one of five status values: `vision_only`, `planned`, `experimental`, `implemented_unverified`, `implemented_verified`. A requirement in this spec has no implied implemented status. `validated_for_named_tests` applies to a model's scientific claim and is distinct from feature implementation status.

**Product rules:**

1. The user may begin with one question, one security, one account, one dataset, one formula or one blank research project.
2. Every useful result provides its source, timestamp, methodology, relevant assumptions and limitations at the appropriate level of detail.
3. Built-in functions and user-created functions operate on the same versioned data, model and permission contracts.
4. A casual user is not forced to learn quant jargon; a professional is not prevented from reaching detailed contracts, source data, logs, code and numerical tests.
5. No research, simulation, AI recommendation, paper order and real-money order is represented as the same type of action.
6. A failure to obtain licensed, current, complete or reliable input is stated, not silently fabricated or filled with future data.
7. Any public claim of replacement or superiority must name the exact workflow, dataset, hardware and comparison protocol.

### 34.2 Coverage, depth and truth are separate axes

Atlas must track three separate measures for each domain: **breadth** (tasks and supported instruments), **depth** (correctness and completeness of a particular workflow) and **data access** (which markets, vendors, geographies, histories and entitlements are actually available). High breadth does not imply depth or access. For example, supporting an options model does not establish access to historical OPRA depth; supporting a startup valuation does not create a complete private-company funding database.

A feature ships only with a task-level description of its completeness, reference tests, data requirements, failure behavior, and fallback or export. Initial product breadth should not weaken correctness of the validated core.

### 34.3 End-to-end work is the true unit of product design

The canonical loop is:

`Discover → Establish evidence → Form hypothesis → Build/compose models → Validate → Simulate consequences → Decide or abstain → Publish/review → Monitor → Re-evaluate`.

Depending on the task, any stage can be omitted. The user can always inspect the object identity and history rather than copy data between incompatible tools. The **research artifact** is the enduring output: a versioned model, strategy, thesis, transaction analysis, financial plan, portfolio decision, application or report with source and experiment lineage.

### 34.4 Expert-level and first-time use must coexist

The shared engine powers role-aware starting workspaces. Different user profiles change recommended actions, explanations, shortcuts, templates and defaults, not financial truth, code execution privileges or access to the open mathematics. A user can switch profiles, open the expert inspector and move between workflows without rebuilding models or moving data.

---

## 35. Users, complete jobs and adoption-critical workflows

### 35.1 Role-contract matrix

| Persona | Start screen / default job | Required completed deliverable | Deep capabilities |
|---|---|---|---|
| First-time investor | Understand a security, investment or goal | Explanation, risk/fee disclosures, scenario comparison | Portfolio concentration, fundamental research, index/fund comparisons |
| Active long-term investor | Compare opportunities and portfolio consequences | Source-backed thesis, valuation, allocation review | Factor risk, tax lots, backtest limitations, alerts |
| Day/swing trader | Find and evaluate constrained setups | Time-stamped watchlist, rule definition, realistic replay, paper trade | Market depth where licensed, trading costs, intraday indicators, risk limits |
| Equity researcher | Analyze a business and its valuation | Auditable company model and investment memo | Segment model, 3 statements, revisions, peer comparison, reverse DCF |
| Credit/fixed-income researcher | Price credit/rates and assess downside | Valuation, curve, spread and risk report | Conventions, cash flows, duration, optionality, issuer credit |
| Quant researcher | Construct and test an original hypothesis | Reproducible strategy/model experiment | Custom operators, features, optimization, GPU, simulation, anti-overfit |
| Portfolio/risk manager | Optimize and monitor a mandate | Positions/P&L, factor, concentration, stress and attribution report | Scenario engines, compliance, governance, liquidity |
| Investment banker | Evaluate a deal | Reconciled transaction model and controlled materials | Comps, LBO, merger, financing, restructuring, diligence, Excel |
| VC / growth investor | Screen and underwrite a company | Capitalization, ownership, cases, investment memo | Financing rounds, dilution, exit values, fund impact |
| PE / private credit | Model acquisition and fund economics | Operating model, debt, covenant, waterfall, returns | Portfolio operations, fund cash flows, private-market benchmarks |
| Real estate / infrastructure | Underwrite an asset | Rent/lease/debt cash-flow and risk model | Location/insurance uncertainty, property twin, development cash flows |
| Household / wealth planner | Understand financial condition and choices | Cash-flow/net-worth and goal scenario plan | Debt, retirement, insurance needs, taxes with jurisdiction and uncertainty |
| Engineer / integrator | Build bespoke financial workflow | Signed/portable research application or model package | API/SDK, IR, sandbox, test harness, permissions, interoperability |

### 35.2 Non-negotiable reference user journeys

**J1: Beginner investment research.** Search a ticker; see identifiable instrument and delayed/live data status; understand what the issuer does, holdings and expense ratios where applicable, financial condition, valuation and major risks; compare with a simpler diversified alternative; save a watchlist or thesis. No misleading personalized investment advice based on incomplete knowledge.

**J2: Institutional equity underwrite.** Select point-in-time issuer and historical filings; inspect revisions and original documents; reconcile GAAP facts and segment mapping; build cash flow and capital allocation forecasts; value under several methodologies; compare to market implied expectations; challenge assumptions; export auditable memo and model; monitor evidence changes.

**J3: Quant experiment.** Build a named universe with delistings and availability clocks; prepare features; compare simple statistical and ML baselines; construct and mutate composed models; conduct purged/sequential evaluation; simulate fills, borrow, fees, market impact and risk; publish full search history including failures; paper-test before any permissioned deployment.

**J4: Trading decision.** Open a chart or scanner; identify exact time and feed source; apply an indicator/strategy with explicit entry, exit and sizing; estimate liquidity/costs; compare historical evidence; simulate order lifecycle; produce a paper-order preview and independent reconciliation. No silent migration from paper to live.

**J5: Banking transaction.** Select buyer, target, security and deal date; construct trading comps and precedent deals; build linked financial forecasts, purchase accounting, sources and uses, financing, synergy sensitivities, accretion/dilution or LBO return cases; version reviewer comments; export Excel and presentation-ready tables without breaking values.

**J6: VC/PE underwriting.** Register legally sourced private-company evidence, round terms, cap-table classes and pro forma financing; model dilution, liquidation preferences, follow-ons and time-to-exit; propagate to fund cash flows, fees and waterfalls; present alternatives and unresolved data gaps.

**J7: Consumer financial planning.** Connect accounts only with explicit consent or import authorized transactions; categorize spending with editable rules; reconcile net worth; model cash-flow constraints, retirement and debt repayment; show assumptions, taxes and uncertainty; allow easy data export and deletion.

**J8: Cross-domain event.** Retrieve a dated weather/energy/industry signal; identify reliable economic relationship edges; construct scenario ranges; propagate into corporate margins, credit, valuation and portfolio risk; distinguish model outputs from verified facts; compare relevant event contracts only if licensed, fully parsed and paper-only.

### 35.3 Workflow acceptance metrics

For each journey, publish task success rate, median and long-tail time to complete, number of required external applications, accuracy against reference cases, source availability, training time, accessibility, and failure recovery. Testing must cover a first-time user and at least one actual domain professional. "No other app needed" is a **measured workflow objective**, not a promise that every private dataset and regulated service is available.

---

## 36. Universal investment model library and coverage contracts

### 36.1 Catalog is a registry, not a flat list of buttons

Atlas will maintain a **Universal Model Registry** of built-in, third-party and user-authored models, strategies, indicators, scorers and templates. Every registry item has a clear `kind`, such as `pricing_model`, `valuation_method`, `forecast_model`, `risk_metric`, `optimizer`, `strategy`, `indicator`, `heuristic`, `accounting_workflow` or `simulation`. These are not equivalent claims of empirical validity.

Required registry fields: name/aliases, family and jurisdiction/asset scope, mathematical reference, equations or executable code digest, input/output schema, shapes/frequencies/currencies/units/conventions, required data quality and history, calibration procedure, parameters/defaults, determinism and seeds, supported execution backends, benchmark fixtures/tolerances, historical and current validity limits, source rights, owner, license, version, dependencies, reproducibility manifest and validation state.

**Implementation coverage must be visible:** `listed_only`, `importable`, `implemented_unverified`, `reference_verified`, `cross_backend_verified`, `empirically_evaluated`, `production_eligible`. A catalog listing by itself is never presented as installed or validated software.

### 36.2 Named catalog targets: corporate valuation and accounting

- DCF; FCFF; FCFE; dividend discount; Gordon growth; multi-stage DDM; H-model; residual income; economic value added; adjusted present value; abnormal earnings growth; trading comparables; precedent transactions; sum-of-the-parts; NAV; liquidation and replacement value; earnings power value; reverse DCF; Graham number; PEG-based heuristics.
- Three-statement model; segment/unit-economics model; operating-driver forecast; forecast/budget/pro forma; cash conversion; capital expenditure/depreciation; working capital; financing/debt schedules; leases; buybacks/dilution; scenario, sensitivity, tornado and break-even analysis.
- Leveraged buyout; merger accretion/dilution; purchase price allocation; sources and uses; deal financing; comparable transaction analysis; recapitalization; restructuring; distressed recovery; project finance and capital allocation optimization.
- Venture capital method; First Chicago; Berkus and Scorecard heuristics; probabilistic startup valuation; shareholder dilution; optionality and milestone scenarios.

### 36.3 Named catalog targets: asset pricing and factor research

CAPM, intertemporal CAPM, consumption CAPM, arbitrage pricing theory, Fama-French three- and five-factor, Carhart four-factor, Hou-Xue-Zhang q-factor, Stambaugh-Yuan mispricing factors, Barra/Axioma-style factor decomposition where licenses permit, statistical PCA factors, macro/fundamental factors, stochastic discount factors, long-run risk, Campbell-Cochrane habit formation. Include factor construction, neutralization, covariance conditioning, exposure measurement, return decomposition, alpha testing, and factor version/definition differences. A commercial branded risk model is not assumed available without license.

### 36.4 Named catalog targets: allocation, optimization and wealth strategy

Mean-variance and efficient frontier, minimum variance, maximum Sharpe/tangency, equal/market-cap/fundamental weighting, Black-Litterman, risk parity, hierarchical risk parity, maximum diversification, robust and distributionally robust optimization, resampled efficiency, mean-CVaR, Kelly and fractional Kelly, liability-driven investing, risk budgeting, target-date glide paths, core/satellite, CPPI, rebalancing bands, tax-loss harvesting, tax-aware asset location, stochastic retirement and withdrawal scenarios, safe-withdrawal heuristics including 4% and Guyton-Klinger. Treat implementation, tax, suitability and shortfall assumptions as first-class inputs.

### 36.5 Named catalog targets: statistics, econometrics and volatility

ARIMA, ARFIMA, VAR, VECM, Engle-Granger and Johansen cointegration, ARCH, GARCH, EGARCH, GJR-GARCH, DCC-GARCH, BEKK, stochastic volatility, realized volatility/HAR-RV, EWMA/RiskMetrics, Kalman and other state-space filters, HMM, Markov-switching systems, change points, dynamic factors, wavelets, fractal/Hurst diagnostics, Bayesian/hierarchical models, survival/hazard models, bootstrap and block bootstrap, mutual information, transfer entropy, lead-lag networks, jump-robust realized volatility, Ledoit-Wolf shrinkage and covariance diagnostics. Statistical significance and forecast utility are separate from the ability to fit a model.

### 36.6 Named catalog targets: quantitative risk and credit

Historical, parametric and Monte Carlo VaR; expected shortfall/CVaR; EVT; copulas and joint-tail risk; stress and scenario tests; beta and tracking error; factor/sector concentration; drawdown risk; liquidity-adjusted VaR; wrong-way and counterparty exposure; CVA, DVA and wider XVA subject to verified conventions; Kupiec/Christoffersen coverage tests; credit PD/LGD/EAD; Merton, Black-Cox, KMV/EDF, Jarrow-Turnbull, Duffie-Singleton, CreditMetrics, CreditRisk+, Gaussian copula/CDO reference cases, migration matrices and survival credit curves; Altman Z, Ohlson O, Piotroski F and Beneish M scores as explicitly scoped screening/forensic indicators.

### 36.7 Named catalog targets: derivatives and volatility markets

Black-Scholes-Merton, Black-76, Bachelier, CRR binomial and trinomial trees, Longstaff-Schwartz, finite differences, Monte Carlo/quasi-Monte Carlo, Heston, SABR, Dupire local volatility, Merton jump diffusion, Bates, variance gamma, Garman-Kohlhagen, Greeks and hedging, SVI/SSVI surface fitting, variance swaps/VIX-style calculations and volatility risk premium. Include payoff engines for vertical spreads, calendars, butterflies, iron condors and appropriate multi-leg options; contract specifications, exercise/assignment, holiday calendars, settlement, margin, volatility smiles and quote-side realism. Exotics only when reference-tested.

### 36.8 Named catalog targets: fixed income and macro

Bond pricing, YTM and effective yield, accrued interest, duration/convexity, key-rate duration, yield-curve bootstrapping, Nelson-Siegel and Svensson, Vasicek, CIR, Hull-White, Ho-Lee, Black-Derman-Toy, Black-Karasinski, HJM, historical LIBOR models with correct legacy labeling and SOFR-based market-model conventions, OAS, MBS prepayment, immunization, callable/putable debt, swaps/caps/floors/swaptions, term structure and scenario shock. Macro: DSGE where practical, IS-LM as a teaching/structural model, Phillips curves, PPP and interest parity, business-cycle states, recession probability, nowcasting, Shiller CAPE, equity risk premium, Fed model, Buffett indicator and Taylor-rule reference studies. Distinguish descriptive indicators from causal policy models.

### 36.9 Named catalog targets: strategies, indicators and execution

- Strategies: value, quality, size, low volatility, dividend, time-series/cross-sectional momentum, trend following, moving-average crossover, mean reversion, pairs/statistical arbitrage, carry, sector rotation, earnings and post-earnings drift, event-driven M&A/index changes, merger and convertible arbitrage, volatility arbitrage, market making, opening-range breakout, Donchian/Turtle channels, seasonality and sentiment/news, option-flow and gamma exposure research.
- Indicators and technical methods: RSI, MACD, Bollinger Bands, stochastic oscillator, Ichimoku, Fibonacci retracement, Elliott Wave, Gann angles/Square of 9, Dow/Wyckoff methods, VWAP, volume profile, on-balance volume, ATR, pivot points, candlestick recognition. The latter are **researchable tools and heuristics**, not validated predictors by inclusion.
- Execution and microstructure: VWAP/TWAP schedules, implementation shortfall/Almgren-Chriss, Kyle, Glosten-Milgrom, Avellaneda-Stoikov, square-root impact models, Roll effective-spread estimates, Amihud illiquidity, order imbalance, queue and partial-fill simulation, transaction cost analysis.

### 36.10 Named catalog targets: ML, evaluation, alternatives and personal finance

- ML: linear/ridge/lasso/logistic, decision trees, random forests, boosting including XGBoost/LightGBM/CatBoost, SVM, k-NN, feed-forward neural networks, LSTM/RNN, transformers, graph neural networks, reinforcement learning, k-means/hierarchical clustering, PCA/autoencoders, NLP/sentiment, LLM-assisted extraction, learning-to-rank and ensemble stacking.
- Validation: ordinary and walk-forward splits, purged/embargoed and combinatorial CV, probability of backtest overfitting, deflated Sharpe, White's Reality Check, bootstrap/permutation, performance attribution including Brinson, Sharpe/Sortino/Calmar/information/Treynor/Jensen/Omega, calibration, proper scoring, rolling IC, drift and regime sensitivity.
- Real estate: cap rate, direct capitalization, NOI, gross rent multiplier, sales/cost/income approaches, cash-on-cash, IRR/equity multiple, DSCR/LTV/debt yield, rent-vs-buy, hedonic/AVM/repeat-sales indexes, development pro forma, waterfalls/promote, FFO/AFFO/NAV, and rule-of-thumb screens clearly labeled as such.
- Alternatives: commodity convenience yield/cost of carry, futures term structures, private-equity J-curve and PME, venture power-law models, insurance and actuarial models, annuity pricing, farmland/timberland, art/collectibles repeat-sales and royalty/music catalog DCF.
- Crypto and digital asset research: stock-to-flow (highly contested), NVT/MVRV, realized capitalization, Puell/SOPR and other cycle indicators, hash ribbons, miner cost models, network/Metcalfe heuristics, token velocity, protocol fee DCF, price-to-fees, TVL ratios, constant-product AMMs, impermanent loss, staking yield, funding/basis, on-chain flows and token issuance/unlock schedules. Rights, network version and chain data provenance apply.
- Personal finance: time value of money, debt amortization, compounding and DCA, household cash flow and net worth, debt snowball/avalanche, emergency reserve, retirement Monte Carlo, insurance needs, Social Security scenarios where applicable, account-type tax rules and withdrawal sequencing.

### 36.11 Catalog release discipline

Implement named models in vertical slices. Ship independent analytical fixtures and clear supported conditions. When multiple published variants exist, use distinct versioned method IDs. Categorize models as `mechanistic/pricing`, `statistical`, `predictive`, `heuristic`, `strategy`, or `accounting`. Preserve their assumptions. An indicator or an in-sample statistical association never receives a certification of investable edge simply because it appears in a catalog.

---

## 37. Model composition, invention and computational research

### 37.1 Universal Model Composition Engine

Every compatible model, transformation, rule, optimizer and external operator must be reusable as a node in a larger graph. Nested composites are themselves versioned `Model` objects, with callable input/output contracts and atomic dependency manifests. Composition modes include:

1. **Chain:** output of one model feeds another, e.g. operating forecast → FCFF → DCF → portfolio scenario.
2. **Parallel:** independent compatible estimators compute alternative outputs, e.g. Kalman trend and boosted signal.
3. **Ensemble:** predictions are combined with frozen/fit-on-training weights, meta-learners or Bayesian mixing.
4. **Conditional routing:** a regime/decision model selects an approved downstream specialist and records the gating decision.
5. **Residual correction:** a second model estimates residuals of an existing model using leakage-safe historical fits.
6. **Hierarchical aggregation:** asset → issuer → sector → portfolio, or property → building → vehicle → fund.
7. **Constrained optimization:** multiple model outputs become explicit objectives and constraints for an allocation, hedging or scenario problem.
8. **Counterfactual/sensitivity:** a structural assumption changes upstream, recomputing only affected downstream outputs.
9. **Graphical/equation/code parity:** model behavior should match across visual, Python/SQL adapter and supported equation paths where the same semantics are expressible.

### 37.2 Composition compiler rules

The FEC checks type and shape, units/currency, observation and public-availability clocks, symbol and instrument identity, forecast horizon, sampling frequency, universe membership, point-in-time training constraints, output distribution coherence, precision, random seeds, side effects, data rights, inference/training feature parity, resource budgets and required permissions. Explicit resampling or unit conversion operators are mandatory when semantics change. The system must not silently feed predictions into observations or connect a future target to a past decision.

**Composition does not mean evidence of improvement.** More layers can overfit, amplify bias and create misleading confidence. Each candidate composite requires a baseline, frozen evaluation rule, logged search history, untouched evaluation period or sequential forward evidence, and meaningful stress and cost sensitivity.

### 37.3 Authoring and sharing

Support visual graph, equation editor, Python/SQL/SDK, reusable package import and optional AI-assisted proposal. Authors may fork models, substitute operators, branch experiments, attach custom indicators and build interactive applications. The system maintains immutable prior versions, explicit dependency pinning, ownership/license and export constraints. Sharing never grants recipients private data rights or automatically installs privileged code.

### 37.4 Model Tournament

A tournament compares candidate models on identical permitted snapshots and task definitions; shows sample size, baselines, errors, calibration, return/risk where relevant, computational costs, throughput, stability, ablations and confidence intervals; records model-selection history including losses; supports champion/challenger and shadow-mode evaluation. Promotion needs task-specific criteria rather than one global score. A model can be mathematically correct and still have no forecasting advantage.

### 37.5 Scientific invention and automation boundary

Automated feature discovery, genetic programming, symbolic regression, hyperparameter search, learned architecture search, adaptive experiment selection, active learning and multi-agent research are allowed only with bounded budgets, no privileged data bypass, experiment logs, source/rights controls and independent validation. LLMs can create proposals but do not prove numerical correctness or trading edge. Preserve negative experiments to reduce repeated exploration and measure genuine research productivity.

### 37.6 Standard experiment artifact

An experiment must be fully reconstructible from a manifest of question/hypothesis, target, decision clock, universe, datasets/vintages/rights, code and model versions, transformations, reference baselines, search trials, train/validation/test boundaries, cost/slippage/borrow assumptions, seeds and hardware, outcomes, errors, uncertainties, safety constraints and exact outputs. Experimental output is distinct from live authorization.

---

## 38. Global financial terminal and market intelligence

### 38.1 Asset and object coverage

Atlas's terminal must support instrument-specific definitions and economics for listed equities, ADRs, ETFs, funds, fixed-income instruments, swaps, options, futures, FX, commodities, crypto, derivatives, structured claims, private securities, real estate assets and portfolios. Nontradable economic indicators and private assets cannot be presented with fictitious live quotes. Support multiple exchanges, currencies, calendars, timezones, settlement conventions and historical symbol changes where source data exists.

### 38.2 Market discovery

- Universal instrument/entity search with disambiguation, identifier mapping and issuer/security distinction.
- Multi-condition screeners with fundamental, technical, derivatives, factor, risk, portfolio, event and custom model predicates; saved and scheduled screens.
- Advanced charts: accurate OHLCV, events, overlay indicators, drawing tools, linked panes, comparative returns, adjusted/raw modes, corporate action annotations, session boundaries, replay and user scripts.
- Options chain, Greeks and IV views backed by correct feed/source, quote dates, contract details and solver flags; spread explorer and scenario payoff.
- Rates, yield-curve, credit-spread, inflation and macro dashboards with vintage semantics.
- Event calendar: earnings, macro releases, economic announcements, corporate actions, maturities and option expirations, with exact time/region and revision history where supported.
- Global mapping and industry networks for locations, logistics, suppliers, facility relationships and regulated public-event research.
- Relevant current headlines, deduplication, entities, claims and source conflicts, preserving rights and observed latency.
- Consistent portfolio overlays: portfolio impact, concentration, known holdings and sources, with stale or restricted account flags.

### 38.3 Streaming and microstructure tiers

Distinguish `historical_bar`, `delayed_quote`, `indicative_quote`, `real_time_quote`, `verified_trade`, `level_2_book`, `full_depth_event_stream` and `simulated_market`. Never claim Level 2 from aggregated OHLC bars or true newswire parity from RSS polling. Streaming workloads require observed exchange timestamps, provider receipt, Atlas receipt, dropped-packet/recovery policies and entitlement checks. Data retention rights constrain replay.

### 38.4 Navigation efficiency

One universal search/command input accepts ticker, ID, organization, formula, analytic command, portfolio, filing, saved model or research question. Context actions include Inspect, Chart, Model, Compare, Backtest, Stress, Explain, Monitor and Export, only where supported. Professional keyboard shortcuts, workspaces, linked panels and programmable command aliases are available without becoming unavoidable clutter for beginners.

### 38.5 Terminal benchmark

Demonstrate searchable current and historical instrument identities; accurate adjustment, session, unit and time behavior; chart latency/viewport performance; two comparative screens; one options/rates workflow; one source-grounded news/event query; explicit coverage/latency missingness. Do not assert competitor data parity without rights and feed comparisons.

---

## 39. Equity, fundamental, accounting and research desk

### 39.1 Company and financial statement intelligence

Create a financial statement graph across fiscal years, quarters, year-to-date and instant values, including restatements, accounting policy notes, segments, geographic/product breakdowns, leases, equity compensation, pensions where applicable, dilution, buybacks, capital expenditures, cash conversion and debt terms. Preserve filings as original evidence and model-normalized interpretations separately. Support global GAAP/IFRS only with explicitly scoped accounting mappings and versioned rules.

### 39.2 Full research workflow

Issuer overview → business and segment economics → historical financials and earnings calls/transcripts where lawful → peer/industry comparison → operating assumptions → three-statement forecast → capital structure → multiple valuation methods → scenario and reverse valuation → moat/competition/industry assessment → catalysts/risks → thesis and memo → monitoring and falsification.

Every scenario presents independently editable assumptions and identifiable model outputs; no forced single target price. The system exposes upside/downside by assumption, implied expectations, terminal-value sensitivity, accounting reconciliations, and alternative evidence. Financial narrative generation can cite models and sources but must not invent management statements or sell-side estimates.

### 39.3 Research-operations features

Research notebooks and annotations linked to filings; earnings-preparation templates; estimate revision histories; cross-company KPI definitions; ownership and Form 4/13F evidence where useful; watchlists; coverage universes; research review/approval; thesis aging and monitoring; reproducible model-to-memo export. If licensed analyst consensus or transcripts are unavailable, show that gap without fabricating them.

### 39.4 Acceptance

A financial analyst must underwrite multiple companies using primary source records and demonstrate that every material number has a source/transform, statements balance within defined tolerance, historical views do not leak amendments, and resulting memo reproduces linked financial values after reopen and export.

---

## 40. Quantitative trading, strategy science and execution research

### 40.1 Research desks and strategy families

Support factor investing, statistical arbitrage, intraday and swing methods, event/earnings, cross-asset signals, rates, credit, options volatility, carry, relative value, market making and systematic portfolio strategies. A strategy is an executable **research definition** with explicit universe, signal generation, clock, rebalancing, position sizing, constraints, order simulation assumptions and benchmark. Do not conflate "strategy exists" and "strategy works."

### 40.2 Market and execution fidelity levels

- **Tier A: Vectorized study.** Fast allocation and factor research, with clear assumptions about rebalancing, historical universe, costs and price timing.
- **Tier B: Event-driven simulation.** Orders, partial fills, cancels, market sessions, fees, cash, positions, splits, dividends, halts, borrow, funding and order rejection.
- **Tier C: Microstructure simulation.** Exact tick/depth event data when entitled, queue position and matching rules, latency and calibrated market impact. No fabricated order-book history.
- **Tier D: Broker paper adapter.** Preview, account/position reconciliation, idempotency, transaction logs, cancellation and kill switch; account must remain demonstrably paper-only.
- **Tier E: Separate live trading extension.** Out of the research core and not required for Atlas completeness. Requires explicit authorization, broker/venue permissions, compliance, risk and operational safeguards.

### 40.3 Automatic strategy discovery safeguards

Algorithms may discover factors, rank setups, learn entry/exit and select model ensembles only through properly separated train/tuning/evaluation periods. Report opportunity count, estimated false discovery, deflated Sharpe/PBO or equivalent, results by time/regime/instrument, slippage uncertainty and capacity. Forward/paper tests must precede live deployment. An attractive historical equity curve without source history and causal timing is not evidence of an edge.

### 40.4 Trader controls

Include real market session calendars, market holidays, timezones, halt/auction rules, tick-size/contract multipliers, borrow availability when relevant, per-order and aggregate risk, position/exposure caps, panic stop, trade log, decisions/events, watchlist lifecycle and alert throttling. Broker adapters must be opt-in, read-only/account-inspection first, paper mode before any live permission, and never expose secrets in research artifacts.

### 40.5 SPX and intraday options specialization

Reusable 0DTE research template: dated SPX and volatility context, exact expiration and settlement conventions, forecast distribution, strike-threshold probability, option bid/ask and size, implied versus modeled outcomes, spread/condor payoffs, fees and margin, filters, event-day constraints, Monte Carlo and similar-day methods, time-of-decision replay, selection-model tournament, and *stand aside* result. Never infer fills from midpoint history or market price as a calibrated physical probability.

---

## 41. Institutional portfolio management, risk and operations

### 41.1 Positions, books and accounting

Support positions, cash, open orders as separate records, cost basis and tax lots, transaction lifecycle, corporate actions, accruals, FX conversion, pricing hierarchy, fund/share classes, benchmarks, liabilities, realized/unrealized P&L and reconciliations. Investment performance must distinguish gross/net, time-weighted/money-weighted, benchmark-relative and adjusted/total-return series. A model target weight does not imply an order or current position.

### 41.2 Portfolio science

Black-Litterman, risk parity, minimum variance, robust/CVaR optimization, liability matching, risk budgeting, factor exposure and attribution, concentration, duration/key-rate/basis, credit transition, liquidity and tail risk, global shock scenarios, regime dynamics, turnover limits, tax sensitivity, transaction costs and investor/mandate constraints. Scenarios must preserve their assumptions and calibration status. Separate stock- and ETF-only portfolios need an explicit shared top-level capital allocation or a declared independent mandate; never implicitly allocate 100% twice.

### 41.3 Professional portfolio operations

Support versioned investment mandates, model portfolios, approval/review workflows, pretrade research checks, performance attribution, benchmark history, portfolio changes, corporate actions, research notes and reporting. Full OMS/EMS, custody, compliance automation and trade settlement are separate potential integration projects, not implicitly solved by analytics.

### 41.4 Risk validation

Independent risk analytics must agree on known portfolios, dates, cash and corporate actions. Publish extreme scenario behavior, covariance conditioning, exposure conservation, limit breaches, crisis periods and liquidity assumptions. A risk scaler is not allowed to silently cause an extreme allocation change without the user understanding why.

---

## 42. Investment banking and transaction intelligence

### 42.1 Required banking workflows

- Comps and precedents with transaction date, consideration and deal-status provenance, currency translation, EV/equity bridge, minority interests and normalization.
- Detailed three-statement forecasts, debt schedules and debt-capacity analysis; debt capital markets and financing terms.
- M&A accretion/dilution with transaction and purchase accounting, dilution, goodwill, debt, financing fees, synergy timing, tax effects and share issuance.
- LBO/management buyout models with sources/uses, debt tranches, mandatory repayments, cash sweeps, operating scenarios, debt covenants, exit multiples, sponsor IRR/MOIC.
- IPO/secondary offerings, recapitalizations, dividend policies, restructurings, solvency/recovery and selective fairness analyses with appropriate professional/legal boundaries.
- Industry-specific models for banks, insurance, SaaS, energy, real estate and infrastructure where separately validated.

### 42.2 Model integrity and deliverables

Each model must reconcile balance sheets, purchase price, sources and uses, cap tables, debt schedules, interest, tax, cash and equity returns. Enable spreadsheet roundtrip with formula or linked-calculation parity tests; PowerPoint/document export with data-binding and approval references; presentation/chart templates; controlled confidential deal-room sources; reviewer notes, freeze dates, sign-offs and permissions. Atlas should improve the workflow without requiring professionals to discard existing spreadsheet templates.

### 42.3 Transaction rights and governance

Deal material is often confidential, privileged, licensed or market-moving. Enforce information barriers, private vs public workspaces, redaction/export restrictions, role-based access, immutable audit trails and no default AI-provider upload. Do not claim built-in legal opinions or investment bank regulatory authority.

### 42.4 Banking reference acceptance

An independent analyst reconstructs an acquisition and LBO from legally shareable example data and reconciles the Excel export with the Atlas result. Vary leverage, purchase price, rates, working capital, synergies and exit; make unsupported inputs explicit; fail numerical and disclosure defects.

---

## 43. Venture capital, private equity, private credit and fund intelligence

### 43.1 Private company identity and evidence

Support company, parent/subsidiary, founder, shareholder, venture fund, manager, financing event, debt instrument, preferred class, option pool, cap-table snapshot and fund entity. Distinguish private user-imported material from public sourced claims; public company and private company data coverage must be tracked separately. No implied access to PitchBook/Carta-like proprietary databases.

### 43.2 Capitalization, financing and venture models

Priced rounds, SAFEs, convertible notes, warrants, option pools, dilution, pro rata rights, liquidation preferences, participation caps, anti-dilution and conversion features, return waterfalls, scenario valuations, follow-on allocation, milestone outcomes and ownership-at-exit. Specific legal document semantics must determine numerical rules; approximate models must be labeled.

### 43.3 Fund and PE operations

LBO and leveraged recapitalization models reuse banking kernels. Fund analytics include commitments, capital calls, distributions, management fees, carried interest, preferred returns, recycling, GP/LP waterfalls, net/gross TVPI/DPI/RVPI/IRR, vintage comparisons, PME, pacing, J-curve and portfolio concentration. Private credit requires covenant schedules, loan interest/fees, collateral, refinancing, PD/LGD, stressed recovery and waterfall tests.

### 43.4 Deal sourcing and diligence

Investment pipeline, company/sector screen, market mapping, evidence notebooks, data-room permissions, investment committee reviews, cap-table simulation, portfolio and board reporting. AI can extract from permitted documents and propose diligence questions, but cannot invent customer retention, revenue or deal terms.

### 43.5 Private-market acceptance

Use a fully specified fictional or authorized cap table with multiple security classes and financing rounds; verify dilution, liquidation outcomes, investor ownership, fund returns, fee distributions and permissions through Atlas models and an independently calculated reference.

---

## 44. Personal finance, wealth and consumer decision support

### 44.1 Consumer promise

A user should be able to understand *where money comes from, where it goes, what they own and owe, what risks they face, and how financial choices change possible future outcomes* without receiving unsupported guarantees or being forced into professional terminology.

### 44.2 Core workflows

- Consolidate user-authorized checking, savings, credit, brokerage, loan, mortgage and retirement data through compatible consented providers, or CSV/manual import. Label synchronization timing and account coverage.
- Cash flow, recurring transactions, cash reserve, transaction review, editable categorization rules, budgeting, subscriptions and reconciliation.
- Household net worth with assets, liabilities, valuations, ownership, dates and confidence.
- Debt amortization, refinance comparisons, interest-rate scenarios, avalanche/snowball payoff and credit considerations with honest fee and tax assumptions.
- Retirement and goal planning with uncertain returns/inflation, contribution schedules, account types, withdrawal order, sequence risk and scenario/Monte Carlo analysis.
- Investing: security and fund research, fees, tax-aware allocation, diversification, risk tolerance as an explicitly supplied preference, cash/liquidity and rebalancing hypotheses.
- Home/rent/buy, education, insurance needs, emergency funds and major purchase scenarios, with region-dependent tax/legal data if and when verified.
- Exportable reports, accessible explanations, privacy controls, correction/override of categorization, and clear provider-disconnection and deletion workflows.

### 44.3 Consumer safety and privacy boundaries

Banking connections use least privilege and explicit user consent; prefer read-only aggregation and no credential handling by Atlas. Financial records are highly sensitive: encryption, local data option, data retention/deletion, selective sharing and minimal telemetry are mandatory. Transaction initiation, taxes filed on user's behalf, insurance recommendations or personalized regulated investment advice require separate legal and operational analysis. Simulators must show forecast uncertainty and avoid false certainty.

### 44.4 Progressive complexity

Default screens show cash flow, net worth, objectives, clear-language analyses and meaningful next actions. Advanced controls expose Monte Carlo distributions, factor exposures, cash-flow equations, scenario assumptions and exported model details. The user's first experience must never display an institutional terminal's full menu tree.

### 44.5 Consumer acceptance

A user imports a bank CSV and brokerage statement or connects an approved aggregator; Atlas reconciles balances, identifies suspicious categorization, models a debt/retirement choice, documents assumptions, and exports a comprehensible plan without exposing raw transaction data to unauthorized plugins.

---

## 45. Adaptive experience, human factors and professional workflow design

### 45.1 Keep exactly four permanent root spaces

`Explore`: inspect assets, companies, accounts, portfolios, data, filings, macro, maps and news. `Studio`: author models, strategies, workflows, reports and apps. `Lab`: train, backtest, simulate, optimize, validate and challenge. `Monitor`: watch data quality, models, positions, theses, accounts, schedules, risk and alerts. Specialized professions receive saved workspace profiles and action suggestions, not distinct disconnected application stacks.

### 45.2 Role-aware starter workspaces

Supported starting profiles: Beginner Investor, Active Investor, Day Trader, Equity Researcher, Credit/Rates Researcher, Quant Researcher, Portfolio Manager, Investment Banker, VC/PE Investor, Real Estate Analyst, Household Planner and Developer. Profiles affect labels, shortcuts, templates, visible modules and default navigation. The profile is portable across devices and can be changed at any time. A role preset must not change model definitions, silently enable live execution, or hide source limitations.

### 45.3 Interface primitives

Universal search and command palette; linked research panels; context-aware inspector; charts with linked time/security; editable tables; source browser and original-document viewer; model graph and equation editor; experiment comparison; source-backed narrative notes; scenario sliders; keyboard shortcuts; reusable dashboards; notebook/code views; version diff; export/share actions; evidence badges for freshness and quality. The status system should be quiet but unambiguous: observed, delayed, inferred, estimated, simulated, stale, unauthorized and unknown are distinguishable.

### 45.4 Disclosure without clutter

Use progressive disclosure with three concentric levels:

1. **Answer:** clear result, assumptions that change the answer, freshness and status.
2. **Inspect:** source, comparison, scenario contributions, formula explanations and method limitations.
3. **Audit:** raw evidence, numeric traces, versions, contracts, code, tests, experiment ledger, hardware and detailed logs.

Advanced mode exposes more at once but uses the exact same computations. No fake "AI confidence," default hidden execution constraints or decorative risk grades. Support keyboard-only operation, screen readers, high contrast, adaptable text size, low-motion, localization and international numeric formats.

### 45.5 User-experience tests

For J1 through J8, conduct novice and expert completion trials. Required measures: task success without help; time-to-first-correct-result; steps and context switches; confusion/error incidence; accessibility completion; path from answer to raw evidence; task completion after failed feeds or canceled jobs; usability on realistic laptop displays. Fix user confusion before adding permanent navigation elements.

---

## 46. Quant Stack compatibility and migration contract

### 46.1 Source and limits

The user-supplied *Quant Stack: Capabilities and Gaps* (dated 2026-11-08) describes four tools: (1) nightly stock/ETF `quant_engine` / `cli.py`; (2) ETF day/swing research application (`tipranks_ETF_quant.py` / `etf_quant_standalone.py`); (3) `ibkr_etf_orders.py` paper-execution workflow; and (4) `spx_0dte.py` with related SPX research views. These are **reported outside Atlas**, not verified Atlas components. The report says its author did not inspect current code. The migration program must first inspect source, licenses, data schemas, test artifacts and current execution behavior. Do not transfer a broker account identifier or secret into the Atlas master spec.

### 46.2 Complete compatibility matrix

| Source system | Reusable research capabilities | Atlas target objects/engine | Migration acceptance |
|---|---|---|---|
| Nightly stocks/ETFs | Point-in-time data gate; split handling; return/volatility; GJR-GARCH/HAR/EWMA blend; Kalman; EVT; factor beta; PCA; Ledoit-Wolf; HMM; cointegration; XGBoost/calibration; constrained risk parity | Data Fabric, Model Forge, Factor/Risk, Quant Lab, Scheduler | Per-step numerical parity on shared fixtures, exact time/adjustment rules, logged source gaps |
| Forecast operations | Monthly retraining; 5-fold purged gate; shadow forecasts; delayed outcomes; rolling IC, PSI, calibration and stability; promotion checks | Experiment ledger, Model Tournament, Monitor | Current candidate remains shadow until objective forward/holdout acceptance; failed runs traceable |
| ETF research desk | Regime/change point; PCA/dynamic factors; mutual information, transfer entropy, lead-lag network; HAR-RV/jump volatility; ARFIMA; momentum, mean reversion, sector rotation, intraday continuation; LambdaRank/XGBoost ensemble | Market Research Pack, Model Forge, Quant Lab | Rebuild dated watchlists, correct learning windows, compare against simple momentum/rules |
| ETF user workflow | Day/swing picks, confidence, entry/exit/stop/hold, signals, collision/crash filter, track record, learned exit, PDF/email/WhatsApp alerts | ResearchApplication, Monitor, reports | Same signal clock and classification, correct asynchronous reports and out-of-sample test |
| IBKR paper routing | Opening-range bracket orders, skips, timed cancellation/flattening, paper-account guard, trade logs | Separate paper `BrokerAdapter`, OMS simulation, audit | No production account access, position/order reconciliation, position caps, idempotency and kill switch |
| SPX 0DTE | Underlying/VIX term structure, 1-minute context, similar-day weighting, strike settlement probabilities, model competition, spread/condor ranking | Options Research Pack, Probability Engine, risk/payoff and event replay | Genuine historical quotes and contracts, settlement rules, fees, bid/ask, calibration, forward test, no synthetic-data performance claim |

### 46.3 Required operator-level compatibility

Preserve or explicitly replace the original named model semantics: `m01` returns, `m02` GJR-GARCH, `m03` HAR, `m04` EWMA, `m05` PCA, `m06` factor betas, `m07` HMM, `m08` Kalman trend, `m09` cointegration, `m10` XGBoost multi-class prediction, `m11` calibration, `m12` EVT tail risk, `m13` Ledoit-Wolf covariance and `m14` risk-parity allocation. Import should declare deviations from historical output, rather than merely expose identically named buttons.

The source engine's reported target constraints include 10% per name, 30% per sector, 12% annual volatility target scaled by stressed-regime probability, expected shortfall 97.5% capped at 2.5% NAV/day, long-only and max gross 100%. These are **reference defaults from the external report**, not universal recommended or immutable Atlas limits. Make each constraint explicit, auditable, testable and user/mandate configurable.

### 46.4 Original operational capabilities to preserve as optional templates

- CLI/API commands for data initialization, nightly run, historical backfill, training, backtest, monitoring, confirm flagged events, status, schedule and scoped reset; use Atlas job/resource/permission contracts.
- Stock and ETF universe definitions with deduplication, historical eligibility and time-bound membership; no ETF/stocks double-allocation ambiguity.
- Step timing, run status, model state, targets, risk/regime, forecasts, symbol drill-down, pairs, model results, data quality and backtest workspaces.
- Real data-input freshness, missing-bar handling, SPY-like market references only when present, custom split overrides, corporate action consistency and total-return dividends.
- Exportable portfolio targets and proposed orders. Target weight output must never automatically turn into a live order.
- Alerts on failed runs, staleness, significant model drift and pending manual review; deduplicated and permissioned notification delivery.
- Reports and communication via user-authorized connectors; no default credential storage in source files.

### 46.5 Fix the 16 reported gaps before claiming production parity

| # | Reported risk/gap | Atlas gate or remediation |
|---|---|---|
| 1 | Engine may read `tos_minute` after feeder shifted to `market.stock_daily` | Source table freshness diff and explicit table contract before each run; compare last session and expected coverage |
| 2 | No validated forecasting advantage (XGBoost won 0/5 folds) | Baselines, shadow tracking, additional real forward data, independent untouched holdout and no automatic promotion |
| 3 | Day strategy negative (reported −0.10R/trade, Sharpe −2.0) with uncapped paper open positions | Default disable trade routing; enforce paper position/risk limits; demonstrate positive forward evidence before any renewed authorization |
| 4 | Swing backtest likely optimistic from regime/full-history fit and learned weights | Recreate as-of training, fixed-default replay, historical universes and independent momentum baseline |
| 5 | No weights-to-order conversion or export | Export targets and proposed shares with holdings, cash, commissions, no-trade bands; paper routing remains separate |
| 6 | Feed intermittently drops symbols | Maintain durable universe and completeness checks; fill only from authorized source, otherwise quarantine stale/missing names |
| 7 | Survivorship bias | Historical constituents, delisted securities and explicitly incomplete-coverage reports |
| 8 | Near-zero exposure in stress regimes from scaler | Explain and test cash-floor/mandate alternatives; never silently impose a new floor that violates user risk policy |
| 9 | Stock and ETF engines each target full capital | Portfolio-of-portfolios allocator or independent capital mandates |
| 10 | IBKR paper orders missing without cause | Expected-versus-placed/filled reconciliation, broker state polling, explicit exception reports |
| 11 | Failed nightly run not alerted | Alert policy tied to durable run state, throttle, ownership, delivery audit |
| 12 | Dividends unadjusted | Verified total-return stream and instrument-appropriate dividend adjustment |
| 13 | Final 12-month untouched holdout not automated | A genuine untouched final period and/or pre-registered sequential forward trial, recorded gate |
| 14 | Large universe memory pressure | Measured resource planner, bounded concurrency, memory-aware fallbacks and explicit hardware bench |
| 15 | SPX options model only synthetic-history tested | Acquire lawful real historical snapshots or accumulate them; calibrate and replay with quote-side realism |
| 16 | Tax and existing holdings ignored | Share/tax-lot accounting, turnover, rebalance bands and clearly scoped tax model |

### 46.6 Validation interpretation

The report's swing backtest recorded approximately 2,474 trades, +0.11R mean result and Sharpe 1.83, with known optimistic biases. The day backtest reported about −0.10R and Sharpe −2.0. These are **reported historic test outputs**, not independently verified proof of profitability, validated data quality, live performance or an Atlas product feature. The SPX model's reported synthetic tests favored simpler baselines. No order-routing capability may be promoted based on these figures.

### 46.7 Quant Stack migration exit criterion

A third party should be able to take the original fixture suite and authorized real-data history, reproduce each model's numerical results within declared tolerances (or document changes), assemble both nightly and ETF compositions, reproduce risk/reporting decisions, inspect shadow and model-gate history, and complete **paper-only** execution reconciliation without leaking credentials or transferring unsafe defaults. The aim is 100% functional research compatibility where legally and technically feasible, **not a promise that original strategy performance was real**.

---

## 47. Enterprise, institutions, connectivity and deliverable interoperability

### 47.1 Professional interoperability

Spreadsheet fidelity is a first-class adoption requirement. Support Excel import/export for structured data, formulas where feasible, typed cells, formatting and audited calculation parity; CSV/TSV/Arrow/Parquet; versioned notebook and Python/TypeScript SDKs; governed report/doc/presentation export; enterprise APIs and webhooks; compatible SQL/database connectors. An exported model that silently changes numbers fails the interoperability gate. Clearly disclose unsupported formula and document features.

### 47.2 Connectors and entitlements

Public sources, user-licensed providers, bank aggregators, authorized brokers, private-company documents, accounting/ERP sources, cloud storage and approved market data must use scoped connectors. Every connector declares identity and permissions, rate/usage limits, geographic restrictions, privacy and redistribution rights, refresh/failure behavior, provenance and detach/revoke controls. **Data access is not implied by the existence of a connector.**

### 47.3 Team workflows and governed research

Workspaces, draft/review/approve states, source and model change logs, comments, shared calculations, frozen results, branches/merges for model specs, approvals for risky changes, persistent audit traces, information barriers and separated private/client materials. User organizations can assign roles and namespaces; shared displays never copy protected data to unintended viewers. Enterprises may require SSO, managed keys, retention policy, backup and recovery with independent security review.

### 47.4 Monitoring and operations

Service health, source quality, ingestion lag, market clock alignment, model drift, computational cost, reproducibility hashes, portfolio reconciliation, job retries, kill switches, on-call alerts and incident/postmortem artifacts. Define workflow-level SLIs/SLOs for interactive retrieval, screeners, model compilation, backtest throughput, UI responsiveness, fresh quotes by provider class, account sync, scheduled-job completion and report delivery. Publish benchmarks with hardware, dataset and entitlement context.

### 47.5 Deployment options

Local-first single-user installation remains viable. Optional remote workers, GPU jobs, hosted synchronization, collaboration and institution-managed installation share exact data and model semantics. Model packaging must work without requiring a central commercial account. Never require consumer data to be uploaded to a hosted service simply to run a local portfolio or equation.

---

## 48. Release strategy, external benchmarks and ecosystem growth

### 48.1 Program sequence: depth before catalog inflation

The following are proposed **dependency stages**, not dates or retroactive claims of completion. Earlier reported Phase 1–3 progress still requires independent repository audit.

| Stage | Priority deliverable | Hard gate |
|---|---|---|
| S0: Verified foundation | Audit current Atlas, correct temporal evidence, security ID, market data and reproducible tests | Real-data end-to-end case with source and numerical audit |
| S1: Research core | Company/ETF terminal, financial statements, valuations, reusable models, graph composition, source export | Independent equity reference case; data-quality and FX/period failures rejected |
| S2: Quant credibility | Factor/risk models, ML tournament, time-safe backtesting, Quant Stack research compatibility, paper-trading safety | No look-ahead/survivorship errors in adversarial fixtures; recorded negative outcomes |
| S3: Multi-asset institutional | Rates, derivatives, credit, optimization, portfolio accounting, attribution/stress | External quantitative references and accounting reconciliation |
| S4: Banking and private assets | M&A/LBO, financing, transaction intelligence, cap tables/funds, real estate | Validated deal, private cap-table and property examples with secure data handling |
| S5: Consumer wealth | Account aggregation, budgeting, planning, retail risk explanation | Privacy/security and numerical reconciliation plus novice user test |
| S6: Advanced economic/AI research | OSINT relationships, real-world scenarios, scientific discovery, value-of-information and agents | Correct causal/evidence labeling, experiments, controlled outcome-quality evaluation |
| S7: Open ecosystem and enterprise | SDK/package registry, signed apps, collaboration, managed operations, optional broker integrations | External developer app; audit/rights/security, reference workflow substitution |

Stages may be developed in overlapping vertical slices, provided dependencies and protected gates are not bypassed. The first public release should favor a very small number of high-quality workflows over a broad unvalidated interface.

### 48.2 Expanded Institutional Capability Benchmarks

Maintain ICB-01 through ICB-20 in earlier sections. Add:

| ID | Test | Pass standard |
|---|---|---|
| ICB-21 Universal Model Catalog | Discover/import and execute built-in and custom models with distinct model kinds | Reference math, metadata, declared coverage and status correct; no false availability |
| ICB-22 Graph Composition | Build the same nested model with visual, equation and SDK paths | Equivalent outputs, lineage, schema checks, reproducible export/reopen |
| ICB-23 Model Tournament | Compare baselines, ensembles and failures on as-of data | No invalid promotion; complete trials, calibrated metrics and bounded search |
| ICB-24 Global Terminal | Search, chart, screen and compare multiple instruments and event data | Correct instrument/time/source status, benchmarks and clear absent feed limits |
| ICB-25 Quant Stack Reproduction | Recreate accepted nightly, ETF, options and paper templates | Source-compatible model fixtures, honest performance status, safe broker isolation |
| ICB-26 Banking Model | M&A and LBO case with spreadsheet export | Sources/uses, debt, earnings, dilution and returns independently reconcile |
| ICB-27 Private Markets | Multi-round capitalization and GP/LP fund case | Security-class and distribution outcomes reproduce reference examples |
| ICB-28 Household Planning | Accounts or imports, debt and retirement scenario | Consent/privacy, reconciliation, uncertainty and novice comprehension verified |
| ICB-29 Portfolio Operations | Multi-asset holdings, targets, P&L, corporate actions and factor risk | No double allocation, cash/positions/fees correct, scenario report reproducible |
| ICB-30 UX Role Continuity | Novice and professional user complete comparable workflows | Same math, progressive controls, no misleading data labels or forced external apps |
| ICB-31 Plugin and Rights | Third-party model/app uses licensed and private datasets | Permission, sandbox, export, attribution and untrusted-code checks pass |
| ICB-32 Operational Reliability | Fail/retry/cancel/stale-feed/recover on realistic workloads | Correct state, resource bounds, source freshness and alerts |

Benchmarks require published reproducibility packages, actual permitted reference data, measurement environment, adversarial cases and acceptance thresholds determined before the final experiment. Where an external implementation or proprietary result cannot be licensed, use independent published mathematics or public reproducible benchmarks rather than fabricated parity claims.

### 48.3 Workflow replacement scoreboard

Maintain an openly inspectable table: `workflow`, `target user`, `incumbent reference`, `data access assumptions`, `Atlas features available`, `benchmark artifacts`, `parity / advantage / limitation`, `known missing functions`, `verified release`. Separately measure time-to-first-correct-answer, task completion, ongoing error rates, speed, hardware cost and support burden. Gold-standard status is earned workflow by workflow.

### 48.4 Community and distribution

Invest in model/plugin author experience, public methodology documentation, reproducible benchmark challenges, discoverable open-source extensions, robust migration tools, clear licensing and research review. Community-contributed models must be moderated for malware, unsafe side effects, rights violations and misleading performance claims. Make it easy to publish a custom model without publishing licensed raw data or private financial records.

### 48.5 Sustainable platform economics

Preserve the open mathematical core and local supported workflows. Potential revenue is from optional licensed data, hosted sync/compute/GPU, enterprise collaboration and governance, integration, compliance features, training and support. Do not promise free provider datasets that have acquisition costs or redistribution restrictions. The objective is to lower the **software and workflow barrier** to institutional-grade research, not invent a legally unrestricted supply of commercial information.

### 48.6 Key strategic risks

- **Scope explosion:** an unfinished generalist that specialists reject. Mitigate with deep vertical slices and audited release gates.
- **Data disadvantage:** incomplete or restricted history, depth and estimates. Mitigate with data-rights-aware BYO and precise coverage dashboards.
- **Numerical or historical error:** realistic-looking but wrong research. Mitigate with independent references, point-in-time tests and public failures.
- **Invisible complexity:** novice UI becomes terminal clutter. Mitigate with profile defaults, progressive disclosure and observed usability.
- **Operational risk:** third-party code, account links and trades. Mitigate with read-only/paper defaults, sandboxing and authority isolation.
- **Model overfitting:** automated search generates apparent alpha. Mitigate with full experiment memory, held-out and forward evaluation.
- **Open-source dependency and maintenance risk:** unsupported libraries and incompatibilities. Mitigate with adapter contracts, license review and stable public APIs.
- **Unverified competitive claims:** claiming to "kill" incumbents without comparable data. Mitigate with public workflow scorecards and limitation disclosure.

### 48.7 Priorities when tradeoffs are unavoidable

Order: security/rights and financial correctness → trustworthy data/time semantics → complete representative user workflow → maintainability/performance → UX refinement → domain breadth → speculative AI/autonomy. The order does not devalue usability; it ensures a beautiful but inaccurate terminal never passes release.

---

## 49. Financial Knowledge Engine: unified, evidence-preserving retrieval

### 49.1 Purpose and architectural boundary

The **Atlas Financial Knowledge Engine (FKE)** is the retrieval, evidence assembly, historical-resolution and factual-grounding layer shared by Explore, Studio, Lab, Monitor, Atlas Intelligence and published Research Applications. It is not a new top-level navigation space, a replacement for the Temporal Evidence Kernel (TEK), or an untrusted AI answer generator. The TEK remains authoritative for original source identity, time, provenance, versions, rights and immutable observations; FKE operates over those records and produces evidence-backed retrieval artifacts. FEC remains authoritative for financial types and calculations.

**Core promise:** A user or model can retrieve the correct evidence from authorized structured, narrative, tabular and historical sources, identify what is missing, verify that the material existed at a required cutoff, and inspect the exact source and relevant transformations. No retrieval path may silently promote a model-generated summary into an observed fact.

### 49.2 Distinct information classes

FKE must preserve distinctions among: (a) raw bytes and source records; (b) parsed tables and normalized facts; (c) source passages; (d) document or model summaries; (e) derived numeric metrics; (f) embeddings and approximate retrieval artifacts; (g) inferred entity relationships; and (h) user-supplied assertions. Each object carries source lineage, source version, original availability time, ingestion time, adjustment or normalization operations, licensing, confidence limitations and visibility policy. Structured XBRL tags and line-item reconciliations are not forced into generic prose chunks.

Every retrieved evidence unit must support `resolve_original`, `as_of`, `inspect_version`, `show_span_or_cell`, `show_transform`, `show_source_rights`, `state_missingness`, and `challenge`. Units for document fragments include source document ID, edition/amendment ID, page/section/character offsets or table cell coordinates when reliably available, language, content hash, and precision of localization. Failure to resolve an exact passage must be reported explicitly rather than fabricating an exact citation.

### 49.3 Retrieval modes and routing

- **Exact identifiers and facts:** entity IDs, securities, CUSIP/ISIN where authorized, XBRL concepts, financial line items, numerical values, report periods, document IDs and original passages; use indexed structured search and exact matching where appropriate.
- **Lexical retrieval:** BM25/inverted indexes for uncommon terms, filing language, tickers, names, legal and contractual wording.
- **Dense semantic retrieval:** embeddings for paraphrased conceptual questions; preserve source-level evidence and do not treat semantic similarity as truth.
- **Hybrid retrieval and reranking:** test lexical+dense combinations against individually strong baselines; calibrate fusion per workload rather than assume more engines means more accuracy.
- **Table-aware retrieval:** link cell values to headers, footnotes, units, periods, segment labels and filing sections; verify table extraction artifacts.
- **Temporal retrieval:** historical document, filing availability, vintage, revision and effective-date selection; prevent later corrections from leaking into prior states.
- **Graph retrieval:** traverse evidence-backed issuer, security, subsidiary, supplier, asset, contract and event relationships with edge confidence/status; do not infer causality from an observed link.
- **Multimodal retrieval:** approved PDFs, slides, charts, maps and images only with extractors and benchmarks demonstrating preserved factual content; preserve original image evidence and localization when possible.
- **Computational retrieval:** use typed SQL and FEC execution to obtain calculated results rather than embedding generated spreadsheets or trusting an LLM to perform financial arithmetic.

The router must select an explicit retrieval plan and record choices, candidate sources, accepted/rejected evidence, unresolved conflicts, latency, cost and cutoff. A default simple pipeline must work offline on CPU. More sophisticated methods are optional and must improve measured workload outcomes.

### 49.4 Historical and contradictory evidence

If a company reports a figure and later amends it, Atlas must preserve both values and clearly describe the target time of the user's query. Queries such as "what was known on date T?" use the selected historical availability policy; queries such as "what is currently restated?" may use later corrections. When two authorized sources conflict, keep the observations and show their respective source classes, report periods, release times and limitations rather than collapsing them to a fabricated consensus.

A user should be able to ask, "What changed between these two filings and which models or investment theses are affected?" FKE returns a dated, source-grounded change set; dependency analysis in FEC identifies affected calculations; ResearchOS proposes replay and review. The changes must not cause unauthorized live trades, retroactively overwrite an older experiment or silently retrain predictive models.

### 49.5 Evidence-grounded financial answering

For an evidence question, the default plan is `identify target and information time -> retrieve -> verify sources -> reconcile terminology/units/periods -> calculate through FEC if necessary -> synthesize with citations -> challenge -> save artifact`. The AI layer may form hypotheses, select tools, explain and critique. The deterministic system must check financial identities, legal/evidence status and executable calculations. Answers include a sufficiently specific source trail, explicit uncertainty, missingness, and a readable summary. `Insufficient evidence` is a supported successful outcome.

### 49.6 User-facing acceptance tests

1. Retrieve an amended issuer filing without confusing original and corrected facts; show the exact source edition.
2. Answer a revenue-growth question with correct period selection and independently verified arithmetic, including when tables and narrative disagree.
3. Detect when a semantic hit is on the right document but the wrong page or metric, then perform a transparent second retrieval or abstain.
4. Construct a cross-document comparison without using future sources in a historical-as-of query.
5. Reproduce the answer and source IDs after a restart with data and method snapshots unchanged.
6. Do not expose restricted source bytes or private documents in a shared app or API response.
7. Quantify retrieval errors and coverage limits on independent evaluation questions, rather than accepting LLM self-rated confidence.

---

## 50. Compression, CDG and evidence-preserving data research

### 50.1 Research mission and established limits

**Compression-Derivative Generation (CDG)** is a research program for representing frequently revised, repetitive and partly structured knowledge in a way that jointly reduces total source, index, cache, data-movement and inference costs while retaining evidence fidelity. It is **not** a proven novel compression algorithm, an established end-to-end RAG improvement, or a guarantee that Atlas can process unlimited data. Its experiments belong in a separate, reproducible research track; candidate improvements must be demonstrated against existing literature and production-quality baselines before becoming Atlas defaults.

The November 8, 2026 exploratory CDG studies reported exact reconstruction on controlled and real-version workloads, meaningful size advantages for shared version layouts relative to independently compressed sources, and improvements on version-change search proxies. These studies primarily used sparse lexical retrieval, synthetic edits and/or one software repository. They did **not** establish financial QA, real pretrained embedding retrieval, SSD p95 access, production-level search indexing or end-to-end LLM inference improvement. Known prior art covers delta graphs, dataset versioning, versioned inverted indexes, access-aware caching and many search-layout optimizations.

### 50.2 Separate data classes, distinct compression policies

| Data family | Fidelity requirement | Candidate storage/retrieval approaches | Mandatory disclosure |
|---|---|---|---|
| Authoritative financial source documents | Lossless original or byte-exact reconstruction | zstd, deduplication, content-addressed chunks, verified version deltas | Original hash, version graph, rights, reconstruction cost |
| XBRL, accounting facts, orders and trade records | Lossless exact numerical/convention semantics | Columnar formats, dictionary encoding, typed compression, suitable codecs | Numeric type, precision, currency, correction history |
| Dense historical price/factor arrays | Exact where required; explicitly bounded approximation only for derived data | Parquet/Arrow, Blosc2, Zarr and format-specific compressors | Splits, total-return semantics, data precision, read amplification |
| Embeddings and search vectors | Approximate allowed with measured retrieval impact | Quantization, compact ANN, USearch/Faiss-style candidates | Recall loss, dimensions, precision, model/version |
| Generated summaries and semantic sketches | Never original evidence | Reproducible summarization, hierarchical retrieval | Source references, generated status, hallucination checks |
| LLM KV/prefill states | Reuse only under compatible identity and position conditions | LMCache/CacheBlend-like evaluated adapters | Tokenizer/model/prompt/version keys, invalidation, memory and overhead |
| Scientific simulation outputs | Declared numerical error budget | Blosc2, Zarr, ZFP where suitable | Error bound, downstream sensitivity, reference outputs |

No speculative codec becomes a mandatory stack dependency. Count metadata, indexes, model weights, cache memory and source snapshots when claiming storage savings. A small archive that forces excessive reconstruction can be worse than a larger selectively readable store.

### 50.3 Three-channel evidence research hypothesis

Investigate shared stable context, exact version changes and provenance-preserving exception passages as separate retrieval channels. The key requirement is not merely to preserve original bytes in storage but to make decision-relevant evidence retrievable and attributable. Full original passages remain available for verification when an index is approximate. Added/deleted facts, negation, numbers, signs, table footnotes and version-sensitive identifiers are high-priority adversarial fixtures.

The three-channel design is a baseline candidate, not a default replacement for BM25 or production hybrid search. A recall advantage on change-intent queries cannot be generalized to every natural-language query or cited as a neural RAG advantage.

### 50.4 Four testable research hypotheses

- **H1: Residual-sensitive semantic filtering.** A shared semantic base plus exact revision/exception channels reduces total index and source bytes while matching full hybrid retrieval evidence recall on versioned corpora.
- **H2: Progressive retrieval with valid uncertainty bounds.** Quantized vectors, score bounds and on-demand decompression can avoid source reads while preserving required candidate coverage under an explicitly defined approximation guarantee.
- **H3: Workload-shaped co-compression.** Jointly optimize physical chunks, version checkpoints, lexical/vector indexing and placement for a measured query distribution, then test robustness under workload shifts.
- **H4: Source-identity-aligned prefill reuse.** Use versioned content identity to avoid repeat LLM prefill work when evidence and prompts permit safe reuse, benchmarking against established serving cache techniques.

A fifth optional direction, **decision-preserving evidence selection**, evaluates whether compression/retrieval choices preserve correct financial arithmetic, scenarios and decisions, rather than just text similarity. Do not overstate financial trading or investment utility: define deterministic reference tasks or carefully bounded simulated decisions with independently established ground truth.

### 50.5 Required prior-art and baseline comparisons

At minimum investigate independently compressed zstd, a solid archive with its random-access limitations, established versioned-index methods, competent BM25 and hybrid retrieval, versioned/temporal indexes, dense-vector retrieval, optimized chunk and metadata layouts, conventional cache policies, and appropriate deduplication-aware alternatives such as IDEA. Compare with relevant literature including *Principles of Dataset Versioning* (PVLDB 2015), *DEX* (SIGMOD 2017), *Compact Full-Text Indexing of Versioned Document Collections* (CIKM 2009), *IDEA* (FAST 2024), and modern query-aware retrieval/KV caching. Verify current code and licenses before importing implementation components.

### 50.6 Reproducibility and falsification gates

Research packages must record source corpus identity and lawful reproduction path, data split, original hashes, compressor versions and settings, source/index/caches bytes, preprocessing and training cost, access workload, CPU/GPU/RAM/SSD specifications, retrieval metrics, exact-match and contradiction checks, sample sizes, seeds, tests, and confidence intervals where meaningful. Use both cold- and warm-cache measurements, including p95 and p99 where sample sizes support them. If model generation is in scope, evaluate end-to-end answer correctness and grounded citations, not just retrieval hit rates.

**Falsify** a proposed technique when: index size and latency worsen at matched recall; an established inverted index wins on the target queries; compression hides exact changed financial values; results fail to generalize to independent datasets; claimed CPU/SSD gains disappear outside toy Python timing; or extra model weights and caches erase the measured savings. Publish negative results.

### 50.7 Integration into Atlas

Initially CDG runs as a replaceable `EvidenceStoreStrategy` and `RetrievalIndexStrategy` in the research benchmark harness. It may be promoted into FKE only after unchanged legal/security contracts, verified exact reconstruction, measured production-like query benefits, upgrade/rollback support, and no reduction in source time semantics. The canonical original evidence remains recoverable regardless of the experimental strategy's status.

---

## 51. Intent-to-Research Compiler and adaptive workflows

### 51.1 Goal

Atlas must reduce the distance between a user goal and a correct completed financial task. The **Intent-to-Research Compiler (IRC)** translates a natural-language request or structured UI selection into an **editable, typed, permission-aware Research Plan**, not a hallucinated conclusion or an unrestricted AI action list. It reuses FEC, UROS, ResearchOS, job orchestration and permissions.

### 51.2 Research Plan contract

A plan includes: normalized user objective; intended output; target entities/instruments; user skill/context; reference date and information cutoff; data sources/rights; required financial types/conventions; candidate model or workflow templates; steps and dependencies; explicit uncertainty and unresolved questions; compute/latency/cost budget; authorized side effects; human approval checkpoints; independent correctness checks; fallback/abstention options; and artifact/replay manifest. Plans are versioned and inspectable before expensive or consequential operations.

The compiler must distinguish `research_question`, `model_build`, `explain`, `compare`, `simulate`, `monitor`, `export`, `paper_order_preview` and `live_order_request`. Only authorized action types may cross a side-effect boundary. An LLM cannot reclassify a live trade as ordinary analysis.

### 51.3 Request understanding and guardrails

- Resolve ambiguous ticker versus legal entity and multiple share classes before binding calculations.
- Ask for one necessary clarification when a key assumption cannot safely be inferred; otherwise show explicit defaults the user can change.
- Identify current-data dependence, provider limits, as-of date, legal eligibility, confidence limits and intended audience.
- Estimate source coverage and workload before computing. Choose a low-cost default plan and an optional deep audit rather than running maximal AI agents unconditionally.
- For personal financial data, require specific consent and never pass sensitive holdings/accounts into public prompts, community models or exports by default.
- If a requested result cannot be grounded or a required feed is absent, offer a supported partial workflow instead of inventing prices or provenance.

### 51.4 Role-specific reference plans

| User request | Initial workflow | End artifact |
|---|---|---|
| "Is this company worth owning for five years?" | Source-aware financials, drivers, valuation, alternative scenarios and risk | Editable underwrite/thesis with X-Ray and monitors |
| "Build and test a regime momentum strategy" | Universe, time-safe features, candidates, purged validation, costs, risk and shadow trial | Full experiment/strategy package, including negative results |
| "Analyze an acquisition" | Sources/uses, target/peer facts, financing and synergies, accretion/dilution, sensitivities | Reconciled deal model and exportable memo/slide inputs |
| "How much house can I afford?" | Authorized household inputs, mortgage/insurance/tax and expense scenarios | Household affordability and uncertainty report |
| "Compare private startup rounds" | Security rights, cap table, liquidation preference, dilution and exit states | Audited capitalization and scenario model |
| "What changed since the original filing?" | Retrieve document versions, exact changed evidence, dependent calculations | Date-aware revision report and impacted research objects |

### 51.5 Plan-to-artifact continuum

Every accepted plan executes as the same typed workflow that experts can construct manually. The user can switch between a concise answer, an inspectable model and a full audit without rebuilding the task. Re-run permissions, source rights, model validation and resource quotas at each change of mode. The UI should display step progress, failure causes and what remains uncertain, not fabricated certainty or decorative agent chains.

### 51.6 Acceptance

Benchmark novice/expert success on the same task; compare the generated research plan against hand-reviewed reference plans; reject missing consent, future data, wrong units, phantom source access and unapproved trade requests. Show actual task completion and correction burden, not merely AI tool-call counts.

---

## 52. Research Integrity Engine: evidence, mathematics and decisions

### 52.1 Purpose

The **Research Integrity Engine (RIE)** unifies the existing Model Auditor, X-Ray, Time Machine and Research Credibility Report into a shared validity and challenge contract. It does not generate a single reassuring "trust score". A correct arithmetic result can have weak source coverage; a fully sourced forecast can have no predictive skill; a statistically significant model can still imply an unsuitable decision.

### 52.2 Four independent integrity dimensions

1. **Evidence integrity:** authorized and correctly identified sources, timestamp/vintage, completeness, conflicts, coverage, missingness, localized citations and unchanged original records.
2. **Computational integrity:** accounting identities, financial types, unit/currency/calendar conventions, corporate actions, numerical precision/tolerances, backend parity and independent reference cases.
3. **Statistical integrity:** dataset selection and survivorship, train/validation/test isolation, experiment multiplicity, baselines, selection history, calibration, drift, capacity and realistic historical costs.
4. **Decision robustness:** objective and constraints, scenario sensitivity, uncertainty, downside/tails, concentration, liquidity, alternative assumptions, do-nothing baseline and model fragility.

Each dimension publishes individual test outcomes `pass`, `fail`, `insufficient_evidence`, `not_applicable`, or `not_run`. The interface presents reasons and affected conclusions. No numerical confidence percentage may be displayed without calibration and a defined event or reference population.

### 52.3 Standard Research Integrity Manifest

```yaml
research_integrity_manifest:
  schema_version: 1
  research_object: "atlas:thesis:<uuid>"
  evaluation_time: "<ISO8601>"
  information_cutoff: "<ISO8601>"
  evidence:
    source_versions: ["<evidence refs>"]
    missing_coverage: ["<limitations>"]
    conflicts: ["<disputed claims>"]
    status: "pass|fail|insufficient_evidence|not_applicable|not_run"
  computation:
    model_digest: "sha256:<hash>"
    reference_cases: ["<test refs>"]
    exceptions: ["<test failures>"]
    status: "pass|fail|insufficient_evidence|not_applicable|not_run"
  statistics:
    experiment_manifest: "<optional ref>"
    holdout_policy: "<defined policy>"
    multiple_test_count: "<known count or unknown>"
    status: "pass|fail|insufficient_evidence|not_applicable|not_run"
  decision:
    objective: "<declared objective>"
    risk_constraints: ["<constraints>"]
    sensitivity_cases: ["<case refs>"]
    status: "pass|fail|insufficient_evidence|not_applicable|not_run"
  approval_state: "draft|reviewed|approved_for_named_use|invalidated"
```

### 52.4 Audit flows and failure handling

- A source correction invalidates affected derived objects, not every unrelated model; preserve older version snapshots.
- Wrong price adjustment, fiscal period, currency or future-available fact should block dependent claims until fixed or explicitly qualified.
- A failed model gate cannot be overridden simply because the strategy generated an attractive simulated return.
- A result based on synthetic data remains visibly synthetic in every derived output, export and presentation.
- The challenge interface must support competing explanations, independent baselines, null results, and reasoned reviewer disagreement.
- Model failures produce repairable evidence: failing test IDs, input diffs, counterexamples, numerical checks and suggested corrective actions.

### 52.5 Release-blocking examples

Unexplained balance-sheet non-reconciliation, a time-traveling filing fact in a backtest, a derived credit spread using incompatible conventions, private-data leakage, an unbounded live order, and a citation pointing to a passage that does not support the claim must all block corresponding production-ready release claims.

---

## 53. Atlas Resource Optimization Engine: the industrial engineering core

### 53.1 Why this is a distinct research asset

The **Atlas Resource Optimization Engine (AROE)** selects compute, data-access, retrieval, storage materialization and experiment scheduling policies under explicit resource and correctness constraints. It makes Atlas an industrial engineering and operations-research testbed rather than merely a bundle of financial libraries. It must be useful on a single laptop and extend to multiple isolated workers only when workloads justify scale.

### 53.2 Formal optimization problem

A practical initial formulation for research plan policy `pi` is:

```text
minimize E[alpha * compute_cost + beta * memory_cost
         + gamma * data_access_cost + delta * elapsed_latency]

subject to:
  permitted_data_and_actions(pi) == true
  peak_ram(pi) <= ram_budget
  peak_vram(pi) <= vram_budget
  estimated_total_cost(pi) <= monetary_budget
  P(required_evidence_retrieved | evaluation_workload, pi) >= 1 - epsilon
  P(unsupported_answer | evaluation_workload, pi) <= eta
  source_time_semantics == valid
  required_numeric_tolerances == satisfied
```

The probabilities are workload-dependent empirical estimates or formal guarantees only where justified; they are not proven for arbitrary financial questions. The `alpha...delta` weights, budgets, risk constraints, candidate choices and information cutoff must be user- or task-declared, versioned and replayable. For high-stakes results, choose robust safety margins and abstention over an uncalibrated optimality claim.

### 53.3 Decision variables and methods

| Decision | Example choices | First methods to benchmark |
|---|---|---|
| Evidence representation | Independent compression, shared versions, selective materialization, canonical archive | Cost models, dynamic programming, threshold policies |
| Retrieval | Structured lookup, BM25, dense, hybrid, temporal graph, exact reconstruction | Simple rules, constrained bandits only after truthful offline evaluation |
| Compute execution | CPU vectorization, SQL pushdown, existing GPU kernels, numerical solver | Profiling, cost-based planning, mixed-integer/convex approaches where justified |
| Cache | Admission, retention, source snapshot, eviction and prefill reuse | LRU/LFU baseline, measured benefit-based policy |
| Experiment schedule | Job priority, concurrency, checkpoint/retry, early termination | Queueing, scheduling heuristics, resource-constrained optimization |
| Research acquisition | Another source, a new test, rerun, stop or abstain | Value of information, Bayesian experimental design |
| Backtest resource profile | Universe size, factor batches, simulation fidelity | Budgeted model selection and capacity planning |

The engine should emit an **execution decision trace** with candidate alternatives, estimated costs, constraints, selected policy, measured realized costs, regressions and missing estimates. Unsupported optimization choices must fall back to the known-correct reference executor.

### 53.4 Model selection is not alpha selection

The model tournament and resource planner must not repeatedly tune on a held-out period or silently prioritize candidates because a backtest happens to look profitable. AROE may optimize *research process cost* and choose the next experiment, but predictive deployment remains governed by RIE and Quant Lab validity gates. Exploration budgets, number of candidates, stopped trials and sequential evaluation must be logged.

### 53.5 Single-device and distributed behavior

Default to deterministic local job queues, measured memory caps, resumable artifacts, explicit caches and predictable cancellation. A GPU is optional. Remote workers or managed accelerators need distinct identity, secrets isolation, rights-aware data movement, hardware-specific numerical parity checks, billing/cost visibility and reproducible job manifests. No promise that a free GPU quota exists or that distributing a task makes it faster.

### 53.6 Experimental IE acceptance

Demonstrate gains against fixed routing, standard cache policies, a no-optimizer plan and an independently profiled strong baseline on mixed workloads. Report quality-matched throughput, p50/p95 time, storage and RAM/VRAM peaks, dollars/energy when reliably measured, failed jobs, decision overhead, and performance under workload shift. Show one case where AROE elects **not** to use GPU, ANN search or an extra agent because the added overhead provides no benefit.

---
## 54. Data Coverage, Integrity and Service Health Center

### 54.1 User promise

The **Data Coverage and Integrity Center (DCIC)** answers, for every displayed number and workflow, "What can Atlas actually observe and calculate, how fresh is it, and where are the gaps?" It is shared infrastructure, not an extra trading screen. Its indicators appear contextually in Explore, Studio, Lab and Monitor, and a detailed diagnostics page is available on demand.

The availability of a dataset, a successful HTTP request or a recent ingestion clock must not be equated with a verified up-to-date financial observation. For each data provider and asset family, state cadence, historical coverage, correction behavior, licenses, source delays and sampling limits.

### 54.2 Coverage dimensions

Coverage is a vector rather than one global percentage. Required dimensions include asset geography/venue, security identity, instrument class, time range, bar granularity, field completeness, point-in-time availability, adjustments, delistings/universe history, corporate actions, financial statement concept/period coverage, benchmark/index membership, market microstructure depth, options chain quality, source licensing, and cross-source disagreement.

For banking/private markets, record whether company, deal, financing, fund, ownership, capitalization, and comparable data are observed, user-entered, modeled or unavailable. For personal finance, record connected account scope, API freshness, transaction categorization rules, institutional connection errors and reconciliation status. Never describe a region-level property estimate as a validated parcel price.

### 54.3 Source pipeline safeguards

- Verify source freshness at the **dataset and symbol/instrument** level. A healthy provider can still have stale security data.
- Detect schema drift and data-table routing errors, such as a feeder writing to a new table while a model still reads the old table.
- Compare latest observed session times across feeder, transformed and consumer views; alert before producing misleading portfolio targets.
- Validate OHLC bounds, volume/split events, exchange calendars, timezone and daylight-saving transitions.
- Do not force a security out of a portfolio because a feeder missed a bar; distinguish a genuinely delisted/invalid asset from temporarily missing input.
- Preserve dividends, capital events, delisting terms, settlement conventions and fund distribution treatments.
- Reconcile portfolio accounting against broker/account statements when authorized; differences are first-class exceptions.
- Track provenance and rights through every export, downstream dataset, generated embedding and model artifact.

### 54.4 Source health state

Canonical statuses: `verified_fresh_for_declared_cadence`, `available_delayed`, `stale`, `partial`, `source_conflict`, `unsupported`, `entitlement_required`, `temporarily_unavailable`, and `synthetic_or_example`. Each indicator explains the affected fields and computations. Prevent a chart with a "live" badge from showing unverified delayed or synthetic values.

### 54.5 Reliability engineering

All production jobs have durable IDs, partial progress, checkpoints, retry/idempotency, cancellation, resource limits, failure alerts and recovery artifacts. The service reports ingestion lag, as-of query latency, model execution failures, background job health, account-sync failures, cache invalidation and data license violations. Define SLOs per workflow and environment, not one marketing latency number. Real-time professional infrastructure requires proven source and execution entitlements; it cannot be simulated by polling retail APIs at high frequency.

### 54.6 Critical acceptance tests

Inject a stale quote, swapped adjustment convention, skipped dividend, delayed macro vintage, missing ETF bar, schema migration, 01:00 daylight-saving boundary, reused source ID, conflicting SEC amendment and expired data entitlement. Correct outcomes are detection, scoped failure or visible qualification, not silent completion. User-facing workflows must show actionable remedies.

---

## 55. Model Experience System and adaptive human-computer interaction

### 55.1 One model, multiple synchronized representations

The **Atlas Model Experience System (AMES)** implements the existing Model Forge promise of visual, equation, table/spreadsheet and code authoring without separate calculation implementations. A saved model has one typed, versioned, immutable definition with editable parameters and reusable operators. Different interfaces must compile to the same FEC plan or state their supported semantic differences explicitly. The model is the object; the UI is a view of it.

Authoring paths:

1. **Template/configuration:** a new user selects a verified valuation, risk, cash-flow, retirement or strategy template and changes guided assumptions.
2. **Table/formula:** cells, named quantities, model schedules, formula inspection and a familiar financial-modeling mental model, with no unsandboxed spreadsheet macro execution.
3. **Visual graph:** data sources, transforms, models, constraints, joins, scenario branches and result views connected by typed edges.
4. **Code/SDK:** documented Python/SQL/registered operators, with exact environment and permissions.
5. **AI-assisted description:** an optional draft that passes the same compiler, source and integrity gates before any claim of correct execution.

### 55.2 Interaction fundamentals

Atlas launches in one of four stable spaces: **Explore**, **Studio**, **Lab**, **Monitor**. The primary default is a search/command interface and a role-aware starter workspace, not 100 panels. Contextual actions are `Explain`, `Model`, `Test`, `Compare`, `Simulate`, `Monitor`, `Export` and `Share`; show only legal and meaningful actions for the selected object.

The progressive path is **Answer -> Inspect -> Audit**. A consumer can use an understandable answer with assumptions; an analyst sees editable drivers; an expert sees equations, execution traces, source rights, backtest configuration and raw artifacts. Standard and Advanced modes expose the same underlying mathematical truth. Switching roles or modes must not alter financial results.

### 55.3 Role profiles as defaults, not silos

| Role | Default home | First complete task | Expert depth on demand |
|---|---|---|---|
| Retail investor | Finances/holdings/watchlist | Understand portfolio concentration or a company's fundamentals | Attribution, risk and modeling |
| Equity analyst | Company desk | Source-backed underwrite and scenario thesis | XBRL, segmentation, assumptions, independent references |
| Quant researcher | Lab/Model Forge | Publish reproducible experiment | Pipeline source, holdouts, full run history, compute profile |
| Trader | Market desk | Evaluate a time-safe setup and market costs | Microstructure/option surfaces, fill models, paper routing |
| Portfolio manager | Portfolio/risk | Reconcile positions and stress exposures | Risk factors, constraints, accounting, compliance and scenarios |
| Investment banker | Deals | Build linked comps and a transaction model | Detailed schedules, sensitivities, source audit, approvals |
| VC/PE professional | Private markets | Diligence and capitalization/return analysis | Preference stack, waterfalls, fund/transaction modeling |
| Research engineer | SDK/Studio | Build and ship a financial research application | IR, profiles, permissions, test and package manifests |

All profiles must support a quick route back to the same source evidence and models. Avoid confusing role changes with data entitlements or permission changes.

### 55.4 Model discovery and guidance

A searchable Model Catalog exposes purpose, relevant asset class, mathematical definition, assumptions, expected input shape, field requirements, reference validations, status, limitations, model version, example cases, performance/cost profile and provenance. Labels distinguish `available_tested`, `available_experimental`, `adapter_required`, `planned`, and `unsupported`. The catalog must not advertise an algorithm as ready merely because it appears in the master spec.

Model composition validates dimensions, time horizons, input/output types, historical availability, randomness, side effects and error propagation. Users can fork a model, compare branches, build nested combinations and export a reproducible package. Failed experiments remain visible.

### 55.5 Beginner-to-expert usability measures

Instrument real task outcomes rather than superficial feature clicks: task completion, time to first correct output, number of unexplained concepts, error correction burden, return usage, keyboard accessibility, screen-reader correctness, source inspection success and cost of required external tools. Test novices and specialists on real workflows. Do not hide critical assumptions solely to make an interface appear minimal.

---

## 56. Workflow Portability, Migration and Professional Deliverables

### 56.1 Why migration is a core product feature

Atlas cannot replace serious financial workflows by requiring every user to recreate their existing spreadsheets, notebooks, data subscriptions, broker records and research documentation from scratch. The **Migration and Workflow Portability System (MWPS)** imports authorized artifacts, maps semantics to native Atlas objects, diagnoses missing dependencies and compares original versus reconstructed results.

### 56.2 Supported import/export families

- **Spreadsheets:** `.xlsx` and CSV schedules, named ranges, ordinary supported formulas, sheet dependencies, financial statements, valuation and portfolio tables. Preserve original files for audit; unsupported macros/functions and circular calculation behavior are explicit blockers or compatibility warnings, not silently changed.
- **Research code:** Python notebooks, scripts and supported libraries imported as sandboxed `Workflow` or external operators, with dependency/environment manifests.
- **Financial feeds and tables:** authorized APIs, Parquet/Arrow/SQL, broker/fund position exports, price histories and provider-specific metadata.
- **Research documents:** PDF/DOCX/presentations and text evidence, with source rights, original bytes, localization and review of extraction reliability.
- **Professional outputs:** Excel models, investment memos, standardized risk reports, pitch/presentation inputs, reproducible notebooks, APIs and rights-aware model/app packages.
- **Collaboration:** model review, comments, version diffs, approvals, private team workspaces, clear ownership and governed sharing. No implicit unrestricted access to client data.

### 56.3 Migration fidelity contract

For each import, produce `source type`, `original artifact hash`, `parsed object count`, `unsupported features`, `mapping decisions`, `source data entitlements`, `numerical reconciliation cases`, `round-trip or one-way status`, `security warnings` and `human-review needs`. If an imported LBO or rates model produces different outputs, show the exact assumptions/formula paths responsible. An attractive UI must never mask calculation drift.

### 56.4 Portable financial application bundles

Bundles have a versioned manifest, reproducible source/IR/model graph, UI schema, permitted dependencies, input rights, required entitlements, test suite, runtime budgets and export permission. An app that depends on licensed inputs can publish fetch references or data manifests rather than redistribute protected bytes. Default package execution is least-privilege and read-only.

### 56.5 External workflow replacement tests

Pilot with real professionals using their own legally obtained representative work: (a) an equity analyst's underwriting workbook; (b) a quant research notebook; (c) a banker transaction model; (d) a portfolio manager's position/risk report; and (e) a household planning sheet. Record conversion time, unsupported functions, independent numeric parity, learning burden, data limits and whether the user could finish without returning to the previous tool.

---

## 57. ResearchOS scientific program for AI, RAG, compression and IE

### 57.1 Research objective

Atlas's research platform must generate academically defensible work, not merely provide a branded finance application. The guiding hypothesis is:

> Can a unified, evidence-preserving compressed representation and adaptive resource-allocation policy reduce the total cost of large-scale AI research while preserving source-time correctness, numerical reliability and decision-relevant evidence?

This is a **research hypothesis**, not an established new algorithm or publication-worthy result. The contribution is only real if independent experiments outperform strong existing alternatives on defined measures.

### 57.2 Research branches

| Branch | Research problem | Required falsifiable result |
|---|---|---|
| A. Compression-aware retrieval | Co-design source storage, indexes and exact revision channels | Better storage/latency/recall frontier on independent workloads |
| B. Resource-aware RAG | Choose lexical, dense, graph and structured retrieval under budgets | Same or better grounded quality for lower measured end-to-end cost |
| C. Decision-aware evidence selection | Preserve financial arithmetic and decision-salient facts under compression | Lower factual/numerical error or regret at matched resource budget |
| D. Historical retrieval fidelity | Retrieve only original publicly available evidence for an as-of date | Measured lower wrong-version and future-leakage error |
| E. Inference reuse | Reuse source-identity-compatible LLM computation | Measured end-to-end prefill savings with identical/validated outputs |
| F. OR experiment optimization | Allocate queries, verification, compute and experiment trials | Lower cost under explicit quality and budget constraints |

Branches may share data and code but need separate baselines, hypotheses, and failure conditions. A proof in Branch A does not prove Branch C.

### 57.3 Evaluation corpora

Start with legally usable SEC filing histories and restatements, XBRL facts, public earnings narratives and carefully constructed question/answer/reference cases. Add FinanceBench, FinQA, TAT-QA or equivalent **only after verifying current dataset and commercial/license terms**. Include outside-finance text/version corpora with independent relevance judgments to test generalization. Archive issuance-time evidence where legally possible; do not reconstruct "historical" snapshots using later revised content without labeling the limitation.

Construct adversarial questions that target: amended numbers, identical boilerplate with changed signs, rare risk disclosures, numeric units, fiscal periods, segment footnotes, contradictory management statements, different issuers with similar names, non-answerable questions and source-availability cutoffs. Use reviewers who did not generate evaluation queries to establish correct evidence labels. Record inter-annotator disagreement where present.

### 57.4 Primary metrics and measurement discipline

**Retrieval:** correct source version, evidence recall@k, precision, exact numeric/negation fact coverage, full source reachability and citation localization.

**Reasoning:** answer accuracy, deterministic computation correctness, evidence support, hallucination/unsupported-claim rate, conflicting-source handling, abstention quality and reproducible source chains.

**Performance:** source bytes, index bytes, vocabulary/model weights, cache resident bytes, compressed I/O, decompression bytes, peak RAM/VRAM, warm/cold p50/p95 latency, batch throughput, build/update cost, compute/energy/currency when measurable.

**Decision task:** objective correctness, sensitivity/regret against a defined ground truth or simulated state, and robustness under missing evidence. Never treat realized speculative return as a ground-truth label for a single company valuation claim.

### 57.5 Experiment design

Use fixed seeds and predeclared splits, untouched tests, independently implemented baseline algorithms, repeated runs and complete configuration/version/environment manifests. Report both absolute metrics and uncertainty, stratify by document change rate and query type, and test drift. Include ablations of exception passages, reranking, dense embeddings, selective reconstruction, caching, cost models and numerical verification. Count model-selection history and guard against repeatedly tuning on the final benchmark.

Positive findings must survive reruns on unrelated corpora, not just synthetic near-duplicate families or human commit-subject proxy labels. Negative results are publishable research outcomes within ResearchOS, even when an Atlas feature is not promoted.

### 57.6 Integration with scientific simulations and other research domains

Atlas's typed computing substrate and AROE can later support experimental design in physics, chemistry, biology, engineering and scientific computing through optional domain packs with appropriate units and solver validation. This does not replace Atlas's financial-first product charter or authorize unverifiable "universal scientific world model" claims. Cross-domain research must pass independent scientific reference cases and security/data-rights checks.

### 57.7 Publication-grade artifacts

Each study exports its hypothesis, relation to prior work, dataset manifest, baseline descriptions, algorithm definition or code, experimental protocol, all trial results, failures, p95/resource profiles, sensitivity analyses, limitations and reproducibility instructions. Submission-ready papers need a defensible novelty claim compared with contemporary literature and honest separation between system integration and algorithmic contribution. No venue acceptance is promised.

---

## 58. Open-source integration and dependency evaluation registry

### 58.1 Integration policy

Candidate repositories are **not installed or approved dependencies** merely because they appear in this list. Before adoption, verify current maintenance, repository identity, license (including transitive dependencies and model weights), API stability, security track record, performance on representative Atlas workloads, source data rights and portability. Use adapters against common typed contracts and publish side-by-side measurements. Existing Atlas evidence and computation remain authoritative.

### 58.2 Initial candidate map

| Domain | Candidates to evaluate | Preferred integration boundary | Decision condition |
|---|---|---|---|
| SEC and financial statements | EdgarTools, Arelle | TEK ingestion and independent XBRL validation | Accurate source/period/filing reconstruction and rights |
| Macro/revisions | FRED/ALFRED official endpoints, fredapi | Time-aware public-source adapter | Original publication and vintage semantics verified |
| Local analytical processing | DuckDB, Polars, Arrow/Parquet | FEC execution and data fabric | Benchmark performance and numerical/semantic parity |
| Lightweight search | SQLite FTS, sqlite-vec | FKE replaceable retrieval backend | Good user-local performance and stable schema |
| Advanced hybrid/graph search | Infinity, LightRAG, selected FAISS/USearch engines | Isolated FKE benchmark adapters | Wins on real corpus and operational budget |
| Document parsing | Docling, specialized table extractors | Ingestion with original byte retention | High table/narrative extraction and citation quality |
| Lossless compression | zstd, OpenZL, Blosc2 | Data-class storage strategy | Verifiable fidelity and cost gains |
| ML/numeric arrays | Zarr, Lance and related formats | Cold/hot typed data stores | Real workload improvement over Parquet/Arrow baselines |
| LLM serving/reuse | llama.cpp, LMCache, compatible serving runtimes | Optional LLM inference backend | Model/tokenizer correctness and measured end-to-end gains |
| Quant models and portfolio | Qlib, skfolio, PyPortfolioOpt, statsmodels, arch | Model Registry / Quant Lab | Benchmarked methods and correct time/data contracts |
| Automated research | RD-Agent, Optuna, PySR | Sandboxed hypothesis/experiment adapter | Measurable improvement over bounded baselines |
| Rates/derivatives/risk | QuantLib, ORE, Strata | FEC instrument-pricing/risk adapters | Convention-accurate independent test vectors |
| Backtesting/microstructure | LEAN, NautilusTrader, vectorbt, HftBacktest, ABIDES | Quant Lab separated execution adapters | Replay and accounting parity on exact fixtures |
| Portfolio/accounting/broker | Authorized data/account APIs, ib_async where suitable | Permissioned broker and sync boundary | Read-only reconciliation first; paper safety; licensed access |
| Entity resolution/OSINT | Splink, GLEIF, OpenFIGI, public-record adapters | Versioned ontology assertion pipeline | Audited match probability and false-merge bounds |
| Historical/lineage reference | Vintage, Dolt, OpenLineage | Benchmark/reference, not new truth store | Demonstrable need beyond existing TEK |

**Default integration sequence:** evidence/XBRL verification -> local analytics -> a simple FKE retrieval baseline -> measured search alternatives -> CDG experiments -> portfolio/quant models -> pricing and institutional engines -> optional autonomous agents and execution. Do not deploy every search engine and database just to make the stack appear advanced.

### 58.3 Component adoption levels

`reference_only`: concepts/tests, no production dependency; `benchmark_candidate`: evaluated in isolated lab; `experimental_adapter`: optional users and controlled fixtures; `verified_adapter`: passing integration/security/numerical tests; `default_backend`: outperforming baselines with rollback; `deprecated`: retained only for compatibility. Each has an owner, version pin, license review, API contract and retirement conditions.

### 58.4 Do-not-import principles

Do not copy source-available noncommercial code into the permissive core, treat an AGPL library as automatically relicensable, scrape restricted feeds, mix incompatible time/corporate-action conventions, or introduce a new mutable database of financial truth without migration and reconciliation tests. Prefer small tested adapters over rewriting proven engines, but retain the right to implement a minimal native component when existing alternatives fail correctness or license requirements.

---

## 59. Product delivery sequence and cross-domain user adoption

### 59.1 A complete first flagship workflow

The release-defining demonstration is:

`Choose a real company -> load original source evidence -> reconcile financials -> build an editable valuation/forecast -> retrieve and verify relevant narrative evidence -> run scenarios and sensitivity -> challenge assumptions and data coverage -> export an auditable memo/model -> save a thesis -> monitor evidence revisions`.

This must work without a mandatory proprietary LLM, account-connected broker or premium-data subscription for the supported public-source reference case. The same underlying model must be usable through a novice UI and a professional inspector. If the software cannot complete this vertical slice, new peripheral dashboards should not displace it.

### 59.2 Release sequence and dependencies

| Gate | Primary delivery | Exit criterion |
|---|---|---|
| G0: Verify the actual repository | Tests, code, migrations, existing manifests and source licenses checked against reported milestones | Independently reproducible baseline and exact implementation-status ledger |
| G1: Real-data integrity | SEC, identity, market/corporate actions, data coverage and reference valuations | Verified source-to-output cases with audit trail; no synthetic "live" data |
| G2: First useful researcher | Explore -> Studio -> audit -> export -> monitor in one complete workflow | External novice and analyst tasks successfully completed |
| G3: Retrieval baseline | Strong structured/lexical/dense baselines, temporal evidence QA | Independent financial question set with measured precision, accuracy and latency |
| G4: Compression/IE research | Replaceable CDG store, AROE cost policies and scientific benchmarks | Measurable gains at matched evidence quality; no regression in exact source rights/time |
| G5: Broad professional quant | Factor library, model tournament, truthful historical simulation and Quant Stack templates | Adversarial backtest, accounting, risk and shadow-model tests |
| G6: Multi-asset/private/household | Rates, options, portfolio risk, banking, private markets, consumer finance | Per-domain independent numerical, security and user tests |
| G7: Ecosystem and enterprise | SDK, signed packages, governed collaboration, optional compute and data | External team develops and maintains a real application without internal patching |

The gates can overlap in work, but no later milestone may bypass upstream semantic, evidence, data-rights, security and benchmark requirements. Avoid date promises unsupported by actual developer capacity or data access.

### 59.3 Workflow replacement scoreboard

For each claimed incumbent workflow, maintain: user persona; problem definition; original workflow; equivalent data entitlements; tasks tested; inputs and outputs; time-to-first-correct-answer; expert completion time; wrong-answer rate; numerical discrepancies; failure handling; software/hardware cost; external-tool dependence; accessibility; and independently verified status. Label `advantages`, `parity`, `limitations` and `unsupported`. Do not advertise universal Bloomberg, Aladdin, CapIQ, TWS or proprietary trading-desk replacement until specific workflows are demonstrably substitutable.

### 59.4 Human factors and user research

Conduct moderated and unmoderated studies with new retail investors, equity analysts, quant researchers, day traders, PMs/risk analysts, investment bankers, VC/PE researchers and finance developers. Each role should have at least one full realistic task and an experienced reviewer. Measure task completion and errors, not just preference surveys. Allow easy import of real authorized work and preserve familiar keyboard and spreadsheet conventions when useful.

### 59.5 Product governance of expanding scope

Every proposed addition declares target user, unique problem, reused platform layer, dependencies, actual data availability, cost and licensing, benchmark fixture, security/privacy implications, comparison against existing Atlas functionality, maintenance owner and exit criteria. Reject vanity features, invented live data, decorative dashboards and code integrations with no proven user value. Keep product depth high while top-level navigation remains stable.

---

## 60. New Institutional Capability Benchmarks and acceptance matrix

Version 3 retains ICB-01 through ICB-32. Add ICB-33 through ICB-48; each needs reproducible public or appropriately licensed fixtures, a clear independent baseline, dated code/data/environment versions, negative tests, quantitative pass conditions and an owner. These are **proposed requirements**, not completed results.

| ID | Benchmark | Core test and failure gate |
|---|---|---|
| ICB-33 | Evidence Version Fidelity | Original versus amended filings and macro vintages selected correctly; false time-travel results rejected |
| ICB-34 | Financial RAG Grounding | Correct source-span/cell support, numerical answers, abstention and conflict handling on independent QA cases |
| ICB-35 | Compression Reconstruction | Byte-exact original recovery with hashes, correct version graph and safe recovery after corruption/failure |
| ICB-36 | Compressed Search Frontier | Total source/index/cache/model bytes, p95 latency and correct-version recall compared with strong lexical/hybrid baselines |
| ICB-37 | Evidence-Salient Changes | Detect rare numbers, negations, footnotes, deleted/revised facts and falsifying evidence without ungrounded summaries |
| ICB-38 | Adaptive Research Plan | Typed plans for retail, quant, banking and research tasks; bad sources/permissions/action types rejected |
| ICB-39 | Research Integrity | Independently pass/fail evidence, computational, statistical and decision checks; explain blockers |
| ICB-40 | Resource Optimization | Show measured quality-matched reduction in cost, time or peak resources versus fixed policies under changed workloads |
| ICB-41 | Data Coverage Transparency | Correct feed freshness, quality, rights, historical universe and source conflict indicators; no synthetic/live confusion |
| ICB-42 | Pipeline Failure Recovery | Detect stale table reads, missing bars, schema drift, bad calendars, retry/cancellation and deterministic replay |
| ICB-43 | Cross-View Model Parity | Visual, formula, tabular and SDK representations match or declare exact unsupported differences |
| ICB-44 | Professional Artifact Migration | Import/validate a working spreadsheet/notebook and reconcile its outputs without hiding unsupported formulas |
| ICB-45 | Novice-to-Professional UX | Role-spanning completion of same research task with equivalent mathematics and meaningful accessibility |
| ICB-46 | Private Data Isolation | Household/deal/team records cannot leak into published apps, unapproved agents or reports |
| ICB-47 | Scientific Generalization | Retrieval/compression advantages replicate across independent finance and nonfinance corpora and adversarial cases |
| ICB-48 | End-to-End Research Substitution | Complete one real equity-research task from original filings to verified memo and monitoring with declared tool/data dependencies |

### 60.1 Benchmark design rules

- Pre-register quantitative thresholds before reviewing final-test results; do not set the passing threshold to the already obtained score.
- Stratify datasets by data age, market regime, document revisions, low-coverage entities, instrument type, user role and hardware.
- Report both per-component measurements and full user-task outcomes; a component optimization can degrade end-to-end experience.
- Count mandatory and optional source data costs, licenses, model weights, GPU/CPU time and cache state when comparing economics.
- Include benchmark artifacts for unsuccessful results, numerical counterexamples, failures and revoked claims.
- Run tests against source snapshots with fixed availability times. Today's restated data cannot be silently used to judge historical research.
- Validate third-party engines against exact test vectors and broker/account operations only with permissioned paper modes where appropriate.

### 60.2 Implementation-status vocabulary

For every public feature and benchmark, publish one of:

`vision_only`: no verified implementation;
`implemented_unverified`: agent/source report without independent audit;
`prototype_verified`: runs selected controlled fixtures, insufficient production proof;
`implemented_verified`: tested in current repository against stated acceptance cases;
`production_eligible`: passed security, correctness, data-rights, performance and operating gates for a named scope;
`deprecated_or_invalidated`: superseded, disabled or failed a required contract.

A test count, commit hash, screenshot, PR or agent report alone does not establish completion. Store the repository revision, test output, independent review and dataset/model artifacts behind each change of status.

---

## 61. Final platform definition and strategic charter

**Version 3 expansion principle:** Atlas should make financial research more correct, accessible, reproducible and economical, rather than merely increasing its feature count. The Financial Knowledge Engine, resource optimizer, research integrity and user-intent layers strengthen the existing eight systems; they are shared capabilities rather than competing applications. AI and compression are evaluated on measured end-to-end outcomes and promoted only after independent benchmarks.

**Atlas Quant is the proposed open-source universal financial operating system:** a source-aware environment for global markets, fundamental research, quantitative modeling, advanced strategy science, institutional portfolio and risk analysis, investment banking, private equity and venture capital, real estate, economic intelligence, and personal financial planning. Its core aspiration is to eliminate unnecessary movement among disconnected tools for *supported, validated, legally accessible workflows*, rather than pretend that proprietary market data and regulated infrastructure are free.

Its shared architecture combines the **Universal Research Object System, Temporal Evidence Kernel, Data Fabric and Rights Engine, Financial-Economic Compiler, Universal Model Registry and Composition Engine, heterogeneous execution runtime, Quant Lab, Research OS and Time Capsule, event/causal/decision intelligence, optional AI research services, and Financial Application Compiler**. Every compatible model can be created, configured, forked, composed, tested, audited, compared, monitored, and packaged as a portable research application.

Atlas must offer a beginner understandable financial tasks through **Explore, Studio, Lab and Monitor**, while permitting a professional to inspect the mathematics, historical availability, compute plans, legal rights and complete experiment history beneath the same view. Personal information, client research and broker permissions are isolated; the research core is free and locally runnable where supported; authorized premium data and managed infrastructure remain optional and transparent.

**Gold-standard status is not self-awarded.** Every claimed replacement advantage must be demonstrated using an external professional workflow, independent numerical references, realistic source entitlements, historical integrity, measured performance, accessibility and reproducibility. A reported implementation is not a passed benchmark; a forecast is not an investable edge; an application package is not legal authority to redistribute private data; a backtest is not a license to trade.

> **One evidence foundation. One interoperable model language and execution contract. One research environment. Many professional and consumer workspaces. Unlimited compatible model invention, constrained by mathematics, evidence, uncertainty, rights, security and real-world testing.**
