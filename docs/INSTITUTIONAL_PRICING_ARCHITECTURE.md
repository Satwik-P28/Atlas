# Institutional pricing architecture

## Scope

Phase 5 implements a narrow, independently verified pricing layer:

* U.S. Treasury par-yield curves from an exact public CSV.
* Hypothetical fixed-coupon government bonds.
* European vanilla options under Black-Scholes-Merton.
* Portfolio covariance risk, stress approximations and constrained optimization.

It does **not** implement callable bonds, MBS, credit models, inflation curves, stochastic
volatility, American exercise, volatility surfaces, XVA or executable dealer pricing.

## Dependency audit

| Candidate | Installed | Decision |
|---|---|---|
| QuantLib | No | Not claimed; no reliable installation in this environment |
| Open Source Risk Engine | No | Not claimed; C++ service/toolchain absent |
| NumPy / SciPy | No | Pure-Python implementations used and independently tested |
| CVXPY / OR-Tools | No | Small active-set solver for ≤ 8 assets |
| pandas | No | Standard library CSV and lists |

The project dependencies remain empty in `pyproject.toml`. This avoids shipping code that
cannot be reproduced by a clean install. The trade-off is slower vector operations and a
small optimizer universe.

## Separation of evidence classes

Every response carries a `data_class`:

| Value | Meaning |
|---|---|
| `official_public_treasury_curve` | exact dated public Treasury observations |
| `hypothetical_fixed_coupon_government_bond` | instrument terms supplied by the user |
| `theoretical_model` | BSM output, not a market quote |
| `synthetic_fixture` | deterministic multi-asset research panel |

Market observations, model parameters, derived metrics and counterfactual shocks are
never merged into one undifferentiated number. The bond response includes the curve
source/hash and labels the instrument as hypothetical.

## Adapter contract

The institutional service is the current adapter. A future adapter must declare:

* instrument types and required inputs;
* units and currency;
* valuation date, calendar and day-count convention;
* operator/API version;
* backend implementation and dependency version;
* numerical tolerances;
* diagnostics and typed errors;
* reproducibility fingerprint and source provenance.

The FEC operators expose the same math to compiler-backed custom models. React only
formats values returned by the server.

## Error behavior

Malformed dates, settlement after maturity, non-finite rates, unsupported optimizer
constraints and unknown runs raise typed API errors. Unsupported scenarios return `null`
with a reason instead of invented numbers.

## Reproducibility

The Treasury file is stored in `fixtures/phase5` with SHA-256
`6775840b76cd7fd41121f61d6f6c60184eca6b2ba49954ec7372c463cbeef34d`. Bond and option
responses contain canonical fingerprints. Persisted runs store the exact input/result JSON.
Applications can be exported as a JSON manifest through the research-object registry.

This proves deterministic replay against the stored fixture. It does not prove the
Treasury file's historical display vintage beyond the archived bytes.
