# Portfolio accounting

## Ledger identities

For every simulation:

```
ending_cash = beginning_cash
            − Σ buy notional − Σ buy commission
            + Σ sell notional − Σ sell commission
            + Σ dividends

ending_equity = ending_cash + Σ(quantity × final close)

total_pnl = ending_equity − beginning_cash
          = realized_pnl + unrealized_pnl − commissions + dividends
```

The simulator publishes `reconciliation.ok` and the individual residuals. A run with a
nonzero residual is an error, not a warning. The 11 Phase 4 tests include a hand-computed
two-trade ledger whose expected cash and P&L are written independently of the engine.

## Trade timing and costs

A signal at close *t* sets a target for *t+1*'s open. A buy uses the next open plus
slippage; a sell uses the next open minus slippage. Commission is `bps × notional`.
Costs are separate ledger entries, never folded into a fake adjusted price.

Shares are whole units; cash is Decimal. A buy that cannot fund the target including
commission buys the largest affordable whole quantity, and if none is affordable the
order is skipped with a reason. This avoids negative cash from rounding.

## Splits

On the effective session, before the open:

* quantity multiplies by the split ratio;
* per-share basis divides by the ratio;
* cash and economic value are unchanged;
* no realized P&L is created.

The test asserts quantity, basis and equity around a 2-for-1 split. A split is applied
once; duplicate action ids are rejected by the loader.

## Dividends

A dividend credits `quantity × per-share amount` in cash on its effective session,
before the close mark. It is not added again through an adjusted price. The engine uses
raw closes and explicit cash dividends, so an adjusted-price series must not be mixed
with this ledger. The test checks the cash credit and total return.

## Metrics

* cumulative return = ending equity / initial capital − 1
* annualized return uses 252 sessions and is only reported when at least 60 sessions
  exist; otherwise it is null with a warning.
* volatility = sample standard deviation of daily simple returns × √252.
* Sharpe = (annualized mean return − risk-free) / annualized volatility; the risk-free
  rate is stored on the run (default 2%) and displayed, never hidden.
* Sortino uses downside deviation below zero.
* maximum drawdown is the minimum of equity / running peak − 1.
* turnover is traded notional / average equity; costs are the sum of commissions and
  slippage.
* benchmark-relative return is strategy total return minus the buy-and-hold total return
  computed with the same bars and costs.

## Known limitations

Annualization on a 2,977-session sample is meaningful as a convention, not a guarantee.
The risk-free rate is a constant, not a term structure. No taxes, financing, borrow,
FX or multi-currency effects. Dividends are only as complete as the stored actions; the
report discloses missing coverage rather than imputing it.
