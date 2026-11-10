# Master Specification v3 priority roadmap

This roadmap follows the verified specification and the measured capability gaps, not phase
numbers. Machine-readable status: `artifacts/master_spec_requirements.json`;
benchmarks: `artifacts/icb_registry.json`; analysis: `docs/MASTER_SPEC_V3_IMPLEMENTATION_GAPS.md`.

## Principle

The v3.0.0 specification describes 61 sections and 48 institutional benchmarks. Thirty-one
benchmarks and roughly half the sections are `vision_only`. Sequencing them by ambition
would produce a wide, shallow product. Sequencing them by **what blocks a user from
finishing a real research task** produces the order below, and each milestone has an exit
criterion that can be executed in this repository.

## P0 — finish the one flagship workflow (Section 59.1)

| Work | Why now | Exit criterion |
| --- | --- | --- |
| Grounded research artefact export (memo/report) built from stored evidence ids | Every step before it exists; the workflow currently ends inside the app | A generated artefact cites observation ids, evidence ids and model versions, and every citation resolves back to a stored record |
| Thesis persistence with revision snapshot | "Save a thesis" exists as a workspace, not as a comparable, replayable research object | A saved thesis reopens at a later revision with the same evidence set and model version, and reports what changed |
| Evidence-change monitoring for a saved thesis | Section 59.1 ends with monitoring; nothing watches after the user leaves | A new filing/revision marks the saved thesis stale, lists affected facts and invalidates only dependent results (ICB-17) |

Exit gate for P0: ICB-48 (end-to-end research substitution) can be **attempted** and its
result recorded honestly, including a failure result.

## P1 — capital-markets correctness that institutions would check first

| Work | Why | Exit criterion |
| --- | --- | --- |
| Three-statement model and comparable-company set (ICB-01) | The specification's first flagship benchmark; today only valuation slices exist | Independent reconciliation of every statement line and the comps table against a reference workbook |
| Fixed income curve and bond valuation (ICB-02) | A terminal without rates is not a financial terminal | Published test vectors matched within declared tolerances |
| Portfolio positions, cash and P&L accounting (ICB-29) | Blocks every portfolio, risk and monitoring feature | No double allocation; cash, fees and corporate actions reconcile across scenarios |
| Data coverage and conflict dashboard (ICB-41, Section 54) | The coverage data exists but is not assembled into one truthful view | Every displayed number can state freshness, rights class and gaps |

## P2 — research depth built on evidence that already exists

| Work | Why | Exit criterion |
| --- | --- | --- |
| Financial Knowledge Engine with abstention (Section 49, ICB-34) | Narrative evidence retrieval is the missing middle of the flagship workflow | Grounded-QA evaluation with gold spans: answers cite spans, abstain when unanswerable, and report conflicts |
| Intent-to-Research compiler (Section 51, ICB-38) | Turns a goal into a typed, permission-checked plan instead of ad-hoc UI clicks | Bad sources and disallowed actions are rejected before execution |
| Research Integrity report unification (Section 52, ICB-39) | The auditor exists but is not one pass/fail surface | Evidence, computational, statistical and decision checks each return an independent finding |
| Model Experience synchronization (Section 55, ICB-43) | Prevents a second, divergent implementation per view | Visual/equation/table/SDK parity proven on one model or explicit declared differences |

## P3 — research programme and portability

Compression/CDG research (Section 50, ICB-35/36/37), resource optimization (Section 53,
ICB-40), workflow migration and spreadsheet/notebook import (Section 56, ICB-44), event and
probability engine (Sections 30–32, ICB-11..18), OSINT (Section 16, ICB-09).

Exit criteria for research work are pre-registered and negative results are published; see
`docs/RESEARCH_AND_COMPRESSION_INTEGRATION.md`. No compression or retrieval claim is made
before an independent, reproducible evaluation.

## P4 — domains that need data entitlement before code

Real estate (Section 33, ICB-19/20), private markets (Section 43, ICB-27), personal finance
(Section 44, ICB-28), GPU benchmarks (ICB-08). These are blocked on licensed or
user-authorised data as much as on engineering; building them first would produce
demonstrations that cannot be verified.

## Explicit non-goals for the next checkpoint

* No new navigation surface and no new evidence store.
* No distributed compute, Redis or a second database: the measured bottleneck is per-point
  materialisation, not the storage engine.
* No public deployment, no rewriting of git history, no change to release visibility.
* No claim of `production_eligible` for any requirement until the security, rights and
  operating gates are run and recorded.
