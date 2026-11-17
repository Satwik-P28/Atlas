# Price Movement Intelligence — "Explain This Move"

Contract: `atlas.price_explanation.v2`
Engine: `src/atlas/research/move_intelligence.py` (`atlas.price_explanation.engine` 2.0.0)
API: `POST /api/securities/{security_id}/price-explanations`
Status: engine, API, chart interaction and panel `implemented_verified` by repository tests
and a real-Chromium acceptance run (desktop and mobile). See
`docs/PRICE_INTELLIGENCE_AUDIT.md` for the exact commands and remaining limits.

## 1. What the feature answers

A user drags over candles (or picks dates) and Atlas answers three separate questions:

1. **What did the price do?** Deterministic statistics over the exact selected sessions,
   on a declared return basis, with the boundary observation ids.
2. **What evidence did Atlas hold?** SEC filings and corporate actions whose *publication
   time* falls inside the interval, plus what is missing from the store.
3. **Which explanations remain unproven?** Ranked hypotheses with a documented relevance
   basis, an explicit epistemic status, and `causal_status: not_identified`.

It never answers "why the price moved". That would require a causal identification design
Atlas does not have for this question.

## 2. Request

```http
POST /api/securities/{security_id}/price-explanations
Content-Type: application/json

{
  "start_session": "2024-03-01",
  "end_session": "2024-06-28",
  "timeframe": "1d",
  "timezone": "America/New_York",
  "price_basis": "split_adjusted",
  "mode": "retrospective_investigation",
  "information_cutoff": null,
  "benchmark_security_id": "SEC-…",
  "peer_security_ids": [],
  "estimation_sessions": 120,
  "evidence_limit": 50,
  "return_convention": "auto"
}
```

| Field | Meaning |
| --- | --- |
| `start_session` / `end_session` | Requested trading-session dates. Reversed input is normalised and reported; non-session dates snap to the nearest stored session and are reported. |
| `timeframe` | Only `1d`. Atlas stores no intraday bars; any other value is refused with `unsupported_timeframe`. |
| `price_basis` | `price` (raw), `split_adjusted`, or `total_return`. Selects the headline statistics; all three are always reported. |
| `mode` | `historical_reconstruction` requires `information_cutoff`; `retrospective_investigation` may show later evidence but excludes it from ranking. |
| `information_cutoff` | Must be on or after `end_session`: a historical run cannot know a close that had not happened. |
| `benchmark_security_id` | Optional canonical security id. Self-benchmarking is refused. |
| `estimation_sessions` | Pre-interval aligned sessions for the market model; ≥ 30, default 120. |
| `evidence_limit` | 1–200 events returned. |
| `return_convention` | `auto` (default), `interval_close_to_close` or `single_session_close_to_close`. `auto` resolves to an interval return for a range and a previous-session return for one candle. |

The request schema forbids unknown fields, so a misspelled `information_cutoff` cannot
silently produce an unbounded retrospective answer.

## 3. Response (selected fields)

```json
{
  "schema": "atlas.price_explanation.v1",
  "selection": { "start_session": "...", "end_session": "...", "sessions": 83,
                 "return_convention": "interval_close_to_close",
                 "price_vintage": { "status": "unverified", "verified_at_cutoff": false },
                 "series": { "policy": "single_provider_held_constant", "source_id": "..." },
                 "start_observation": { "observation_id": "MOB-…" } },
  "price_statistics": {
    "requested_basis": "split_adjusted", "basis_label": "...",
    "interval_return": -0.059165, "sessions": 83, "calculation_sessions": 83,
    "return_convention": "interval_close_to_close",
    "annualized_volatility": 0.28, "max_drawdown": -0.11,
    "volume": { "average_to_trailing_median": 1.4 },
    "basis_reconciliation": { "raw": -0.0592, "split_adjusted": -0.0592, "total_return": -0.0511 }
  },
  "benchmark": { "status": "available", "return": 0.02, "aligned_sessions": 83,
                 "coverage_ratio": 1.0, "excess_return_arithmetic": -0.079 },
  "market_model": { "status": "available", "beta": 1.13, "r_squared": 0.41,
                    "expected_return_compounded": 0.021,
                    "abnormal_return_difference": -0.080,
                    "abnormal_return_ratio": -0.078,
                    "attribution_convention": "compound alpha + beta x benchmark daily return",
                    "estimation": { "window_rule": "aligned sessions strictly before the selected interval" } },
  "events": { "items": [ { "event_id": "FIL-…", "relation": "in_window" } ],
              "coverage": { "news_archive": { "status": "unavailable" } } },
  "observations": [ { "observation_id": "OBS-interval-return", "value": -0.059165 } ],
  "hypotheses": [ { "rank": 1, "epistemic_status": "hypothesized",
                    "causal_status": "not_identified",
                    "relevance": { "tier": 2, "basis": "…", "supporting_evidence": ["FIL-…"] } } ],
  "rights": { "export_allowed": false, "restricted_sources": ["…"],
              "unregistered_sources": [], "reasons": ["…"] },
  "warnings": [ { "code": "price_vintage_unverified_at_cutoff", "message": "…" } ],
  "reproducibility": { "hash": "…", "components": {
      "selected_series": { "points": ["…"] }, "context_series": { "points": ["…"] },
      "benchmark": { "window_points": ["…"], "estimation_points": ["…"] },
      "sources": ["…"], "calculation": { "version": "atlas.price_explanation.calculation.v2" } } }
}
```

## 4. Numerical semantics

**One series, one provider.** The interval is built with `evidence.select_series`, which
fixes the provider at the request's end date and holds it constant. Competing providers
stay stored and are reported in `series.excluded_providers`; they are never spliced in.

**Compounding.** A multi-session return is `last / first - 1` on the declared basis.
Individual daily returns are never added. `test_multi_session_return_is_compounded_not_added`
pins 100 → 110 → 121 = 21%, not 20%.

**One session.** A one-candle selection is a one-session move only when the previous
eligible session is stored. Atlas then measures the previous close to the selected close
and reports `return_convention: single_session_close_to_close`, with the previous
observation as the start boundary. If no previous eligible session exists, the return is
`null`, `return_convention` is `unavailable`, a `single_session_previous_unavailable`
warning is emitted and `refusals` names the reason. Atlas never assumes a flat prior close
and never reports a fabricated 0%.

**Three bases, never conflated.**

| Basis | What it measures |
| --- | --- |
| `price` | raw close-to-close; mechanical across a split |
| `split_adjusted` | split-adjusted close change, dividends not reinvested |
| `total_return` | dividend-reinvested index level change, not a price |

A raw request that spans a recorded split carries `raw_basis_spans_corporate_action`.

**Volatility.** Sample standard deviation of daily returns × √252, reported with that
definition. One session yields `null`, not zero.

**Overnight versus intraday.** Split-adjusted opens and closes; the product of the two
components telescopes from the session before the window, so it describes *where* the move
occurred, not an additive decomposition.

**Volume anomaly.** Mean in-window volume over the trailing median of sessions strictly
before the window; no claim is made without trailing history.

**Benchmark alignment.** A benchmark return is claimed only when at least two benchmark
observations fall inside the interval, at least two sessions are shared with the security,
and the shared sessions cover at least 50% of the security's window. Otherwise the status
is `unavailable` or `insufficient_alignment`, no `return` key is emitted, and a warning
names the reason. A benchmark with no in-window observations is never reported as a 0.0
return or as `available`. The benchmark return, excess return and model window are all
computed on the shared sessions, so both sides describe the same days.

**Market model and cumulative attribution.** OLS of aligned daily simple returns over
sessions **strictly before** the selected interval, most recent `estimation_sessions`. The
response reports the estimation first/last session, aligned availability, coefficients and
R². Cumulative attribution compounds the model's own daily expected return
(`alpha + beta × benchmark_daily`) over the aligned window and reports
`expected_return_compounded`, `abnormal_return_difference` (security return minus expected)
and `abnormal_return_ratio` (multiplicative). `beta × compounded benchmark return` is
reported only inside `first_order_approximation`, because its cross terms do not vanish
and it is not the abnormal return. A benchmark with effectively constant returns has no
identifiable slope and yields `unavailable` rather than a fabricated beta. Different
currencies block relative statistics entirely.

**Peers.** Each `peer_security_ids` entry is measured on its own stored series over the
same date bounds, with its own provider and its own corporate actions under the same
cutoff. A peer with no observations is `unavailable`; a peer in another currency is
reported with `comparable: false` (no FX conversion is implied). Peers are not adjusted
for differing session counts, which is stated per peer.

## 5. Temporal semantics

Two modes, never mixed:

| Mode | Evidence rule |
| --- | --- |
| `historical_reconstruction` | Requires `information_cutoff`. Filings are admitted by **acceptance time** ≤ cutoff. Corporate actions require a recorded `availability_time` ≤ cutoff; those with unknown availability are excluded and counted. Later evidence is excluded. |
| `retrospective_investigation` | Every in-window event is shown. Later amendments of an in-window accession appear as `relation: "subsequent"` with `known_at_range_end: false` and are **excluded from the hypothesis ranking**. |

`relation` is decided by publication time, not `filed_date`: an amendment accepted after
the interval cannot be a contemporaneous event. An after-hours acceptance stays on its own
calendar date; it is not shifted to the preceding session.

**Price vintage.** Atlas stores the latest revision of each session, not the provider's
publication history. `selection.price_vintage` is therefore always
`status: unverified`, `verified_at_cutoff: false`, with
`provider_publication_vintage: null`. In historical mode the response adds
`price_vintage_unverified_at_cutoff` and a limitation stating that prices are filtered by
session date, not by vendor vintage. The UI shows a visible "price vintage unverified"
badge. No claim is made that a vendor had published a value by the cutoff.

Historical AI analysis is not implemented. The response emits
`parametric_hindsight_disclosed` to record that document filtering alone cannot certify a
language model's pretraining had no knowledge of later events.

## 6. Evidence and hypotheses

The timeline contains SEC filings and corporate actions. Every item carries an event id,
publication time and precision, source id, amendment relation and `epistemic_status:
observed`.

**Material versus routine.** Only `MATERIAL_FORMS` (8-K, 10-Q, 10-K, 20-F, 40-F, 6-K,
S-1/S-3/S-4, proxy and tender forms, SC 13D, NT filings and amendments) can support an
explanation. Form 4, Form 144 and similar administrative filings are shown in the timeline
and explicitly not treated as evidence of repricing.

**Hypothesis tiers** (documented relevance, no probabilities):

| Tier | Basis |
| --- | --- |
| 1 | A computable corporate action with a certain arithmetic price effect |
| 2 | A material SEC disclosure published inside the interval |
| 3 | Market-model co-movement or a remaining residual (explicitly not a cause) |
| 4 | Volume at least 2× its trailing median (descriptive only) |
| 5 | Abstention: no material company-specific evidence in the store |

Every hypothesis has `epistemic_status: hypothesized`, `causal_status: not_identified`,
supporting/contradicting evidence ids, inputs and limitations. No field represents a
probability.

## 7. Rights and reproducibility

Rights are decided over **every contributing source**: the selected series, the context
series used for estimation and volume, the benchmark (window and estimation points), every
peer, every corporate action and every filing. `rights.export_allowed` is true only when
all of them are registered, carry a recorded licence, and are `public_domain`,
`project_authored` or `permitted`. An unregistered source id is treated as
`redistribution: unregistered` and fails closed; a missing licence also fails closed. The
response names `restricted_sources`, `unregistered_sources`, `missing_licence_sources` and
per-source `reasons`. The UI disables the export control and shows the reason.

`reproducibility.hash` is SHA-256 over the normalised request (including basis, mode,
cutoff, benchmark, peers, estimation length, evidence limit and return convention), the
calculation and market-model versions, every selected and context observation with its
revision and content hash, benchmark window and estimation points, peer points, corporate
actions with availability and supersession, event identities, and the full source records.
Identical stored state reproduces it; a provider correction, a new filing or a changed
rights record changes it.

Deterministic warning codes include `range_snapped_to_nearest_session`,
`single_session_interval`, `single_session_uses_previous_session`,
`single_session_previous_unavailable`, `missing_sessions_in_window`,
`price_vintage_unverified_at_cutoff`, `date_precision_availability`,
`benchmark_not_requested`, `benchmark_no_comparable_observations`,
`benchmark_alignment_insufficient`, `estimation_window_too_short`,
`benchmark_currency_mismatch`, `subsequent_evidence_excluded`,
`evidence_filtered_by_cutoff`, `unregistered_source`, `source_licence_missing`,
`news_archive_unavailable`, `analyst_consensus_unavailable`,
`restricted_source_not_exportable`, `parametric_hindsight_disclosed`.

## 8. Chart interaction

`web/src/components/Chart.tsx` adds an overlay **only when Explain mode is enabled**; with
the mode off, the chart keeps its native wheel, pinch, crosshair and drawing behaviour.

Mapping uses supported Lightweight Charts v5 APIs: `timeScale().coordinateToLogical(x)`
for the drag, `logicalToCoordinate(index)` for the band, and
`subscribeVisibleLogicalRangeChange`/`unsubscribe…` for redraw. Fractional indices snap to
the nearest existing bar; either drag direction yields an ordered range. The band is a DOM
element sized to the selected candle positions, so it survives zoom, pan and resize.

Keyboard: focus the chart, arrow keys move, Shift+arrow extends, Enter commits, Escape
clears. Date inputs beside the chart are the accessible alternative and stay in sync with
a drag. Switching security or timeframe clears the selection.

Pure mapping logic lives in `web/src/components/chartSelection.ts` and is unit-tested
(reversed drag, clamping, single candle, selection invalidation, keyboard extension).

**Browser acceptance.** `web/e2e/price-explanation.mjs` drives real Chromium against the
running app and passes 19 checks: desktop load, untouched normal chart, both drag
directions, one candle, keyboard range, wheel zoom with an active band, resize, share-class
change, three repeated investigations, benchmark-unavailable state, delayed API with a
visible loading state, injected API error with retry recovery, authorized export download,
restricted-export disabling, closing the mode, mobile layout without horizontal overflow,
touch drag, and mobile rights. Screenshots are written to `artifacts/`. The run found and
fixed a real defect: the feature stylesheet was imported only by the equity page, so on the
company page the overlay had zero height and could not be dragged. The styles now live in
the global `styles.css`, and the mobile metric card wraps long policy tokens.

## 9. Explicit non-capabilities

- No intraday selection, bars or microstructure analysis.
- No news, press-release, consensus or macro-release source; coverage reports them as
  unavailable and the engine abstains instead of inventing a headline.
- No causal identification, counterfactual simulation or probability attached to a
  hypothesis.
- No saving of an investigation as a research object; the auditable JSON report is
  exported instead.
- No peer selection in the UI. `peer_security_ids` is implemented and tested at the API
  and engine level: each peer is measured on its own stored series over the same date
  bounds, and a different currency is reported as `comparable: false` rather than
  converted without an FX convention. The panel does not yet offer a peer picker.
- No provider-vintage archive. Historical mode qualifies the price-vintage claim instead
  of proving it.
- No ICB-65…ICB-75 benchmark is marked passed. The browser run is feature acceptance, not
  a scored benchmark result.

## 10. Acceptance record (2026-11-17)

| Check | Command | Result |
| --- | --- | --- |
| Python suite | `.venv/bin/python -m pytest -o addopts='' -q` | 732 passed, 1 skipped, 0 failed (733 collected) |
| Feature tests | `.venv/bin/python -m pytest -o addopts='' -q tests/test_price_explanations.py` | 34 passed |
| Inventory | `.venv/bin/python scripts/verify_test_inventory.py` | baseline 699 + feature 34 = 733, verified |
| TypeScript | `cd web && npx tsc -b --noEmit` | exit 0 |
| Frontend unit | `cd web && npx vitest run` | 5 files, 50 passed |
| Production build | `cd web && npm run build` | exit 0 |
| Browser | `cd web && node e2e/price-explanation.mjs` | 19 passed, 0 failed |
| Spec checksum | `.venv/bin/python scripts/verify_master_spec.py` | v3.2, 357970 bytes, SHA-256 verified |

The browser run used Chromium 1248 with a locally extracted library bundle because the
container has no root and no system Chromium dependencies. That is an environment detail,
not a product dependency.
