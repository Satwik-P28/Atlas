# Atlas audit — Price Movement Intelligence program (P0)

Date: 2026-11-17
Scope: the repository state inspected before building **Explain This Move**, the P1 slice
of the master directive. This document records what was actually run and read. It is not a
claim that the wider program (factor research, ML integrity, compute, institutional risk)
was implemented.

## 1. Verification baseline

| Check | Command | Result |
| --- | --- | --- |
| Python suite | `.venv/bin/python -m pytest -o addopts='' -q` | **718 passed**, 1 warning, 134 s |
| TypeScript | `cd web && npx tsc -b --noEmit` | exit 0 |
| Frontend unit tests | `cd web && npx vitest run` | 5 files, **50 tests passed** |
| Production build | `cd web && npm run build` | exit 0 |
| Demo database | `.venv/bin/python scripts/build_terminal_db.py --db var/atlas.db --force` | 5 issuers, 10,580 bars, 14,977 filings |
| Live API | `POST /api/securities/{id}/price-explanations` against the demo DB | 200, `atlas.price_explanation.v1` |

The only initial failures were four Phase 6 learning tests, caused by the optional
`learning` extra (`numpy`, `scipy`, `scikit-learn`, `pyarrow`) not being installed. After
`pip install -e ".[dev,terminal,learning]"` they passed. No test was skipped, weakened or
excluded.

## 2. Implementation status ledger

Statuses use the vocabulary in `ATLAS_MASTER_SPEC.md` §60.2. "Verified" here means
repository tests exercise the stated behaviour at this revision, nothing more.

| Capability | Status | Evidence / boundary |
| --- | --- | --- |
| Canonical price selection (one decision, alternatives reported) | `implemented_verified` | `src/atlas/market/evidence.py`, `tests/test_phase9_2_6_market_contract.py` |
| Canonical daily series (one provider held constant) | `implemented_verified` | `evidence.select_series`, `tests/test_phase9_2_7_market_series.py` |
| Split and total-return adjustment, never applied twice | `implemented_verified` | `src/atlas/market/adjust.py`, `tests/test_market.py` |
| Trading calendar + gap detection | `implemented_verified` | rule-based XNYS/XNAS; unscheduled closures are a documented limitation |
| Corporate actions | `implemented_verified` for split/reverse split/dividend; merger, spin-off and distribution are **declared, not computed** | `src/atlas/market/actions.py` |
| SEC filing/evidence kernel with availability precision | `implemented_verified` within archived fixtures | `src/atlas/evidence/kernel.py`; no independent XBRL challenger exists |
| **Price Movement Intelligence engine** | `prototype_verified` | new `src/atlas/research/move_intelligence.py`, 19 adversarial tests |
| **Price-explanation API** | `prototype_verified` | new `POST /api/securities/{id}/price-explanations`; additive OpenAPI path |
| **Chart interval selection (drag/keyboard)** | `implemented_unverified` | `web/src/components/Chart.tsx` + pure mapping tests; **no browser acceptance run** |
| **Investigation panel** | `implemented_unverified` | renders all required sections; not clicked through in a browser |
| News archive, press releases, consensus, estimate revisions | **absent** | no licence; the response says `unavailable` and abstains |
| Macro-release calendar linked to a security | **absent** | no point-in-time release source wired |
| Intraday bars / intraday selection | **absent** | requests for any timeframe other than `1d` are refused |
| Factor definition registry and point-in-time universe | not started in this slice | unchanged from the prior state |
| Research trial ledger, purged CV, deflated Sharpe | partial prior work, not audited here | `learning_*`/`validation_attempt` tables exist |
| CPU/GPU compute benchmarks | not started in this slice | no measurement was made; no speedup is claimed |
| Institutional factor/fixed-income risk validation vs ORE/QuantLib | not started in this slice | unchanged |

## 3. Material findings, and what this change did about them

1. **No repository licence.** There is no `LICENSE`, `NOTICE` or `COPYING` file at the
   repository root, and `pyproject.toml` declares no `license` field. The directive's
   premise that this is an MIT-licensed repository is therefore **unverified**. Code may
   not be described as MIT-distributed without an explicit legal decision. This is a
   documentation/legal blocker, not changed by this slice.
2. **Routine filings were being ranked as explanations.** On live demo data, Form 4, Form
   144 and ARS filings produced a tier-1 "material disclosure" hypothesis. Fixed: the
   timeline still shows every filing, but only `MATERIAL_FORMS` (8-K, 10-Q, 10-K, 20-F,
   S-1, proxy and tender forms, and their amendments) can support an explanation. A
   regression test pins this.
3. **A degenerate benchmark produced a confident-looking nonsense beta.** With an
   effectively constant benchmark return, the variance was ~1e-38 and division produced
   beta ≈ −0.057. Fixed: near-zero benchmark variance is now unidentified
   (`market_model.status = unavailable`) instead of numerically fabricated.
4. **Filing events were classified by `filed_date`, not publication time.** An amendment
   accepted weeks later could appear as a contemporaneous event. Fixed: relation is
   decided by acceptance time; later revisions are `subsequent` and never enter the
   ranking.
5. **Empty alignment windows crashed adjustment.** A short history with no pre-interval
   session raised `cannot adjust an empty series`. Fixed; the model reports
   `estimation_window_too_short` instead.
6. **OpenAPI gate.** Adding one route changed the contract fixture. The fixture was
   regenerated and the diff verified: **one added path, no removed paths, no changed
   existing path**; the operation count moved 156 → 157 and paths 142 → 143.

## 4. Financial-period and XBRL semantics

The evidence kernel stores `availability_precision` (`exact` / `date` / `unknown`),
adjudicates conflicting facts, and rejects facts not available at a cutoff. That is the
foundation the new feature relies on for *timing*, not for *numerical fact selection*.

What this slice deliberately did **not** do:

- It did not add an independent XBRL parser (Arelle, xbrlkit) to challenge Atlas's fact
  selection. No such dependency is installed.
- It did not resolve the known semantic questions: instant versus duration facts,
  dimensional/segment contexts, fiscal-period ambiguity, annual-versus-quarterly context,
  amended filings, and company-specific extensions.
- Consequently the price-explanation engine cites **filing identity** (accession number,
  form, acceptance time) and market observations. It does not parse a financial number out
  of a filing to "explain" a move. That is a deliberate boundary: an explanation must not
  rest on unverified XBRL semantics.

These remain open P0/P3 work items, alongside `docs/EVIDENCE_RECONCILIATION.md`,
`docs/VALUATION_ELIGIBILITY_CONTRACT.md` and `docs/HISTORICAL_AVAILABILITY.md`.

## 5. Market-data and source-rights assessment

- SEC EDGAR evidence is a U.S. federal work and is treated as `public_domain`.
- The demo series is `synthetic-demo` / `project_authored`; the API and UI label it
  synthetic. No synthetic series is presented as observed market performance.
- Restricted vendor bytes are cached under `var/` only, which is ignored by Git.
- Every price-explanation response carries a per-source rights decision. If **any** cited
  source is restricted, `rights.export_allowed` is false and the export control is
  disabled; the derived statistics remain inspectable locally.
- No news archive, consensus history or macro-release calendar is licensed. The engine
  emits `news_archive_unavailable`, `analyst_consensus_unavailable` and the matching
  coverage status rather than inventing headlines or expectations.
- No redistribution agreement was reviewed. Hosting this feature publicly with restricted
  provider data would require one.

## 6. Specification integrity

- `ATLAS_MASTER_SPEC.md` is present (v3.1.0). No ICB-65…ICB-75 benchmark was added and no
  benchmark count or pass claim was changed.
- Draft PR #2 / `docs/atlas-v3-2-research-price-intelligence` is **not present** in this
  checkout (`git log --all -- 'docs/atlas-v3-2*'` finds no such document). The proposed
  v3.2 Appendix E was therefore treated as a design reference only. Nothing was merged and
  no concurrent work was overwritten.
- The new feature is documented as its own contract
  (`docs/PRICE_MOVEMENT_INTELLIGENCE.md`), not as master-spec conformance.

## 7. Remaining blockers and the next concrete milestone

Blockers:

1. Browser acceptance of chart selection — mouse, touch, pen, keyboard, reversed drag,
   zoom/pan with an active selection, resize, timeframe switch, and mobile layout were
   **not exercised in a browser**.
2. Licensed historical news/consensus/macro evidence, without which "what happened" is
   structurally incomplete.
3. Provider-vintage archive, without which point-in-time price reconstruction cannot prove
   what was public on a date.
4. Repository licence decision.

Next milestone: complete a browser-level acceptance run for the selection interaction and
the panel, then add a licensed, cutoff-aware news source behind the existing event contract
— before any factor-research or compute work is started.
