"""Pure financial mathematics used by the institutional research layer.

The functions here do not read the database, call the network or mutate state. They are
the independently testable numerical core behind the compiler operators and the HTTP
API. Floating-point results are returned with explicit conventions; Decimal accounting
remains the responsibility of the execution ledger.
"""

from .curves import (
    CURVE_SCHEMA,
    BondAnalytics,
    CashFlow,
    YieldCurve,
    add_months,
    analyse_bond,
    bootstrap_par_curve,
    load_treasury_csv,
    shock_bond,
)
from .options import (
    OPTION_SCHEMA,
    bsm_greeks,
    bsm_price,
    implied_volatility,
    option_parity_residual,
)
from .statistics import (
    annualized_return,
    annualized_volatility,
    covariance_matrix,
    expected_shortfall,
    historical_var,
    max_drawdown,
    portfolio_returns,
    solve_linear,
)

__all__ = [
    "BondAnalytics",
    "CURVE_SCHEMA",
    "CashFlow",
    "OPTION_SCHEMA",
    "YieldCurve",
    "add_months",
    "analyse_bond",
    "annualized_return",
    "annualized_volatility",
    "bootstrap_par_curve",
    "bsm_greeks",
    "bsm_price",
    "covariance_matrix",
    "expected_shortfall",
    "historical_var",
    "implied_volatility",
    "load_treasury_csv",
    "max_drawdown",
    "shock_bond",
    "option_parity_residual",
    "portfolio_returns",
    "solve_linear",
]
