# ADR 0013 — Versioned, server-side indicator registry

- **Status**: accepted (Phase 2)
- **Date**: 2026-11-04

## Context

The terminal plots moving averages, Bollinger bands, RSI, MACD, VWAP, volatility, returns
and drawdown. Indicators are easy to get subtly wrong (seeding, warm-up, annualisation,
dividend basis) and users need to know exactly what a line means. Two implementations — one
in Python for the API, one in TypeScript for the chart — would drift and make the
mode-invariance guarantee meaningless.

## Decision

`atlas/terminal/indicators.py` is the only implementation. Each indicator is registered
with a stable identity, a formula string, parameter schema, outputs and a warm-up rule:

| Key | Outputs | Parameters (defaults) | Version |
|---|---|---|---|
| `sma` | `sma` | `window` (20, 2–400) | `atlas.indicator.sma.v1` |
| `ema` | `ema` | `window` (20, 2–400) | `atlas.indicator.ema.v1` |
| `bollinger` | `middle`, `upper`, `lower` | `window` 20, `num_std` 2 | `atlas.indicator.bollinger.v1` |
| `rsi` | `rsi` | `window` (14, 2–200), Wilder smoothing | `atlas.indicator.rsi.v1` |
| `macd` | `macd`, `signal`, `histogram` | `fast` 12, `slow` 26, `signal` 9 | `atlas.indicator.macd.v1` |
| `vwap` | `vwap` | rolling `window` (20) | `atlas.indicator.vwap.v1` |
| `rolling_volatility` | `volatility` | `window` 20, `annualization` 252 | `atlas.indicator.rolling_volatility.v1` |
| `rolling_returns` | `return` | `window` 1 | `atlas.indicator.rolling_returns.v1` |
| `drawdown` | `drawdown` | — (running peak) | `atlas.indicator.drawdown.v1` |

Rules:

1. **Basis is the displayed series.** `raw` and `split` views compute on displayed prices;
   `total_return` computes on the displayed index level (base 1.0), using each session's
   volume for volume-weighted indicators. An indicator is never computed on one basis and
   drawn on another.
2. **Warm-up is missing, not zero.** Points before enough observations exist are omitted
   from the series (the chart simply has no point). If the whole window is too short the
   result says `insufficient_data: true` and explains why.
3. **Two identities.** `version` identifies the formula; `calculation_id` is a hash of the
   version, parameters and input-series fingerprint. Two different parameter sets cannot
   share a calculation id, and repeating the same request reproduces it exactly.
4. **Strict parameters.** Unknown keys, wrong types, out-of-range windows and
   `fast >= slow` are 422 validation errors. The registry is the whitelist; clients cannot
   pass arbitrary functions or expressions.
5. **One request, many indicators.** `POST /api/securities/{id}/market` returns the bars,
   the actions applied and every requested indicator with its formula and params, so the
   chart legend and the "method" table are generated from the same response.
6. **No backtesting.** There is no signal generation, position sizing or P&L. The
   indicators are descriptive series.

## Alternatives considered

* Client-side maths with a shared WASM module — still two runtimes to test, and the API
  would lose the ability to state the formula alongside the data.
* A pandas/talib dependency — a heavy native dependency for nine formulas that fit in
  ~400 readable lines; also harder to pin semantics.
* Storing computed series — they would become stale the moment a bar or action changes,
  and Phase 1 already treats derived evidence as something to invalidate.

## Consequences

* Chart latency is a server round trip (~30 ms locally for a 1Y series with four
  indicators); acceptable.
* Reference tests (`tests/test_terminal_indicators.py`) recompute SMA, EMA, Bollinger,
  VWAP, RSI extremes, MACD identity, returns and drawdown by hand, so a formula change
  fails loudly. Adding an indicator requires a registry entry, a version id, tests and a
  formula string.
* RSI uses Wilder smoothing (not a simple mean of gains/losses) and EMA seeds with the
  first SMA; both are stated here because reasonable implementations differ.
* Downsampling (above 2,000 points) happens before indicators are computed, so a very
  long range's indicator values are computed on the displayed sampled series, not the full
  series. That is explicit in the response's `truncated` flag and warning.
