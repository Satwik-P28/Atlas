# Atlas audit — Price Movement Intelligence program (P0/P1)

Date: 2026-11-17
Scope: the repository state inspected and verified for **Explain This Move** on the
`review/price-intelligence-v3.2` branch. This document records what was actually run,
what a real browser exercised, and what remains open. It is not a claim that the wider
program (factor research, ML integrity, compute, institutional risk) was implemented.

## 1. Verification baseline

| Check | Command | Result |
| --- | --- | --- |
| Python suite | `.venv/bin/python -m pytest -o addopts='' -q` | **752 passed, 0 failed, 0 skipped** (752 collected), 149 s — integrity pass |
| Feature tests | `.venv/bin/python -m pytest -o addopts='' -q tests/test_price_explanations.py` | **35 passed** |
| Integrity tests | `.venv/bin/python -m pytest -o addopts='' -q tests/test_price_evidence_integrity.py` | **18 passed** |
| Test inventory | `.venv/bin/python scripts/verify_test_inventory.py` | observed 752/35/18; baseline 699 **reconstructed**, **verified** |
| TypeScript | `cd web && npx tsc -b --noEmit` | exit 0 |
| Frontend unit tests | `cd web && npx vitest run` | 5 files, **50 tests passed** |
| Production build | `cd web && npm run build` | exit 0 |
| Browser acceptance | `cd web && node e2e/price-explanation.mjs` | 19 checks passed at `747871b`; **not rerun** (no browser in this environment) |
| Spec checksum | `.venv/bin/python scripts/verify_master_spec.py` | v3.2, 357970 bytes, SHA-256 **verified** |
| Live API | `POST /api/securities/{id}/price-explanations` against the demo DB | 200, `atlas.price_explanation.v3` |
| End-to-end acceptance | `.venv/bin/python scripts/accept_price_integrity.py` | **32 checks passed, 0 failed** |

The four Phase 6 learning tests that failed before were caused only by the optional
`learning` extra (`scipy`, `scikit-learn`) missing in the restored environment. After
installing it they pass. No test was skipped, weakened or excluded to make this table green.

## 2. Implementation status ledger

Statuses use the vocabulary in `ATLAS_MASTER_SPEC.md` §60.2. "Verified" here means
repository tests and, where stated, a real browser exercise the behaviour at this revision.

| Capability | Status | Evidence / boundary |
| --- | --- | --- |
| Canonical price selection (one decision, alternatives reported) | `implemented_verified` | `src/atlas/market/evidence.py`, `tests/test_phase9_2_6_market_contract.py` |
| Canonical daily series (one provider held constant) | `implemented_verified` | `evidence.select_series`, `tests/test_phase9_2_7_market_series.py` |
| Split and total-return adjustment, never applied twice | `implemented_verified` | `src/atlas/market/adjust.py`, `tests/test_market.py` |
| Trading calendar + gap detection | `implemented_verified` | rule-based XNYS/XNAS; unscheduled closures remain a documented limitation |
| Corporate actions | `implemented_verified` for split/reverse split/dividend; merger, spin-off and distribution are **declared, not computed** | `src/atlas/market/actions.py` |
| SEC filing/evidence kernel with availability precision | `implemented_verified` within archived fixtures | `src/atlas/evidence/kernel.py`; no independent XBRL challenger exists |
| **Price Movement Intelligence engine** | `implemented_verified` | `src/atlas/research/move_intelligence.py`, 35 adversarial tests + 18 integrity tests |
| **Original SEC document pathway** | `implemented_verified` against archived fixture bytes; **not** against live EDGAR | `src/atlas/research/filing_evidence.py`; locator, hash, spans, cutoff and rights enforcement |
| **Saved price investigations** | `implemented_verified` | `src/atlas/research/investigations.py` on the UROS contract; reproduce/impact/export |
| **Price-explanation API** | `implemented_verified` | `POST /api/securities/{id}/price-explanations`; additive OpenAPI path |
| **Chart interval selection (mouse/touch/keyboard)** | `implemented_verified` in Chromium | `web/src/components/Chart.tsx`, `chartSelection.ts`, 19 browser checks |
| **Investigation panel** | `implemented_verified` in Chromium | desktop + 390×844 mobile, loading/error/empty/export states |
| Source-rights decision over every contributor | `implemented_verified` | fails closed for unregistered, unlicenced or restricted sources |
| News archive, press releases, consensus, estimate revisions | **absent** | no licence; the response says `unavailable` and abstains. Other providers were assessed by class in `PRICE_EVIDENCE_INTEGRITY_PASS.md` §3 |
| Macro-release calendar linked to a security | **absent** | no point-in-time release source wired |
| Intraday bars / intraday selection | **absent** | requests for any timeframe other than `1d` are refused |
| Provider price-vintage archive | **absent** | `selection.price_vintage` is always `unverified`; historical mode qualifies the claim |
| Factor definition registry and point-in-time universe | not started in this slice | unchanged from the prior state |
| Research trial ledger, purged CV, deflated Sharpe | partial prior work, not audited here | `learning_*`/`validation_attempt` tables exist |
| CPU/GPU compute benchmarks | not started in this slice | no measurement was made; no speedup is claimed |
| Institutional factor/fixed-income risk validation vs ORE/QuantLib | not started in this slice | unchanged |

## 3. Material findings, and what this change did about them

1. **No repository licence.** There is no `LICENSE`, `NOTICE` or `COPYING` file at the
   repository root, and `pyproject.toml` declares no `license` field. The directive's
   premise that this is an MIT-licensed repository remains **unverified**. Code may not be
   described as MIT-distributed without an explicit legal decision. This is a
   documentation/legal blocker, not changed by this slice.
2. **Routine filings were being ranked as explanations.** Fixed in the first pass: the
   timeline still shows every filing, but only `MATERIAL_FORMS` (8-K, 10-Q, 10-K, 20-F,
   S-1, proxy and tender forms, and their amendments) can support an explanation.
3. **A degenerate benchmark produced a confident-looking nonsense beta.** Fixed: near-zero
   benchmark variance is unidentified (`market_model.status = unavailable`).
4. **Filing events were classified by `filed_date`, not publication time.** Fixed: relation
   is decided by acceptance time; later revisions are `subsequent` and never enter the
   ranking. After-hours acceptance stays on its own date and is not shifted to the previous
   session.
5. **Empty alignment windows crashed adjustment.** Fixed: a short history reports
   `estimation_window_too_short` rather than raising.
6. **Export rights ignored most contributors and failed open on unknown ids.** Fixed in this
   pass. Rights now cover the selected and context series, benchmark window and estimation
   points, every peer, every corporate action and every filing. A source id that is not
   registered is `redistribution: unregistered` and fails closed; a missing licence fails
   closed; an empty source set cannot authorize an export. Tests cover unknown ids, missing
   licences and a restricted peer blocking the whole export.
7. **A benchmark with no comparable observations could show a fabricated zero.** Fixed:
   fewer than two in-window observations, fewer than two aligned sessions, or coverage below
   50% yields `unavailable` / `insufficient_alignment` with no `return` key and no
   `available` status.
8. **A one-candle selection reported a flat 0% return.** Fixed: the previous eligible
   session supplies the start close and the response declares
   `single_session_close_to_close`. With no previous session, `interval_return` is `null`,
   `return_convention` is `unavailable`, and a refusal names the reason.
9. **Cumulative attribution used `beta × compounded benchmark`, whose cross terms do not
   vanish.** Fixed: the model's daily expected return is compounded over the aligned window;
   abnormal return is reported as both an arithmetic difference and a ratio. A test checks
   the result against an independent scalar computation and pins the first-order figure as a
   separate approximation.
10. **The reproducibility manifest was too thin to replay the calculation.** Fixed: it now
    includes the normalised request, calculation and market-model versions, all selected and
    context observations with revisions and content hashes, benchmark window and estimation
    points, peer points, corporate actions with availability and supersession, event
    identities and full source rights records. A provider correction changes the hash.
11. **Historical mode could imply vendor prices were available at the cutoff.** Fixed:
    `selection.price_vintage` is always `unverified`, historical mode emits
    `price_vintage_unverified_at_cutoff`, the limitation says prices are filtered by session
    date rather than vendor vintage, and the UI shows the badge.
12. **The feature stylesheet was imported only by the equity page.** The browser run caught
    it: on the company page the overlay had zero height, so dragging did nothing. The styles
    moved to the global stylesheet; a long policy token also overflowed its mobile metric
    card, now wrapped.
13. **The audit's own test counts had drifted** ("718 passed / 19 tests"). Fixed: the
    machine-readable inventory is `artifacts/test_inventory.json`, checked against actual
    collection by `scripts/verify_test_inventory.py`.

## 4. Financial-period and XBRL semantics

The evidence kernel stores `availability_precision` (`exact` / `date` / `unknown`),
adjudicates conflicting facts, and rejects facts not available at a cutoff. That is the
foundation the feature relies on for *timing*, not for *numerical fact selection*.

What this slice deliberately did **not** do:

- It did not add an independent XBRL parser (Arelle, xbrlkit) to challenge Atlas's fact
  selection. No such dependency is installed.
- It did not resolve instant versus duration facts, dimensional contexts, fiscal-period
  ambiguity, amended filings or company-specific extensions.
- The engine cites **filing identity** (accession number, form, acceptance time) and market
  observations. It does not parse a financial number out of a filing to "explain" a move.

These remain open P0/P3 work items, alongside `docs/EVIDENCE_RECONCILIATION.md`,
`docs/VALUATION_ELIGIBILITY_CONTRACT.md` and `docs/HISTORICAL_AVAILABILITY.md`.

## 5. Market-data and source-rights assessment

- SEC EDGAR evidence is a U.S. federal work and is treated as `public_domain`.
- The demo series is `synthetic-demo` / `project_authored`; the API and UI label it
  synthetic. No synthetic series is presented as observed market performance.
- Restricted vendor bytes are cached under `var/` only, which is ignored by Git.
- Every response carries a per-source rights decision over **all** contributors. Unknown or
  unlicenced sources fail closed; the derived statistics remain inspectable locally but the
  resolved observation values may not be exported.
- No news archive, consensus history or macro-release calendar is licensed. The engine emits
  the matching coverage status rather than inventing headlines or expectations.
- No redistribution agreement was reviewed. Hosting this feature publicly with restricted
  provider data would require one.

## 6. Specification integrity

- Draft PR #2 (`docs/atlas-v3-2-research-price-intelligence`, head `59c6df3`) was fetched
  and merged into this review branch with `--no-ff`; `main` was not changed.
- The v3.2 specification adds Appendix E and preserves Sections 1–61 numbering. The merge
  touched only `ATLAS_MASTER_SPEC.md`, `docs/MASTER_SPEC_GATE.md`,
  `docs/MASTER_SPEC_TRACEABILITY.md` and `scripts/verify_master_spec.py`.
- `scripts/verify_master_spec.py` passes after reconciliation: 357970 bytes and SHA-256
  `6ab1a00569a29830deda050c44eaa93dc0f65081be53966ed2a6d00b164447e2`.
- **No ICB-65…ICB-75 benchmark is marked passed.** Appendix E labels them proposals, and the
  browser run is feature acceptance, not a scored benchmark result.

## 7. Browser acceptance record

`web/e2e/price-explanation.mjs` ran against the live app (Vite + FastAPI) in Chromium 1248:

| Area | Checks |
| --- | --- |
| Desktop chart | load; normal pan/zoom untouched with Explain off; left→right drag; right→left drag normalised |
| Selection semantics | one candle uses the previous close; keyboard Home/Shift+Arrow/Enter commits |
| Layout | wheel zoom with an active band; resize; 390×844 mobile without horizontal overflow |
| Instruments | share-class change clears the investigation |
| Robustness | three repeated investigations; benchmark-unavailable state; 1.4 s delayed API with loading; injected 500 with retry recovery |
| Export | authorized download parsed and verified; restricted response disables the control and shows the reason |
| Touch | pointer drag on a touch/mobile context renders the panel and rights |

Screenshots retained in the repository: `artifacts/final-panel-desktop.png` and
`artifacts/final-panel-mobile.png`. The run used a locally extracted Chromium library
bundle because the container has no root; that is an environment workaround, not a product
dependency.

## 8. Remaining blockers and the next concrete milestone

Blockers:

1. Licensed historical news/consensus/macro evidence, without which "what happened" is
   structurally incomplete.
2. A provider-vintage archive, without which point-in-time price reconstruction cannot prove
   what was public on a date. Today the claim is qualified, not proven.
3. Repository licence decision.
4. ICB-65…ICB-75 scoring. The feature exists and is browser-verified, but none of those
   benchmark proposals has been executed or scored.

Integrity pass (2026-11-17): publication-time policy reconciled with the Temporal
Evidence Kernel, timeline ordering fixed, original-document resolution and citable spans
added, saved investigations added, and 18 adversarial tests plus a 31-check end-to-end
acceptance recorded. No ICB-65…75 status changed. Live EDGAR retrieval and the browser run
remain undemonstrated here.

Next milestone: add a licensed, cutoff-aware news source behind the existing event contract,
then execute the Appendix E benchmark proposals without changing Sections 1–61.
