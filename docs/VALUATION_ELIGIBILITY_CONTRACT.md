# Valuation Eligibility Contract v2

`atlas.valuation_eligibility.v2` is a machine-readable record of what may be claimed about
a valuation. It is attached to every equity analysis and packaged with the research
application.

## States

| State | Meaning | Promoted by |
| --- | --- | --- |
| `unsupported` | No implemented methodology is admissible for this business model. | Classification only |
| `insufficient_source_coverage` | A method exists but required reported inputs are missing. | Coverage check |
| `methodologically_eligible` | Method is admissible and all required inputs exist. | Coverage + classification |
| `arithmetically_verified` | Independent recomputation of every component agrees. | Component audit |
| `economically_reviewed` | An explicit review of assumptions and limitations has been recorded. | Human/recorded review |
| `independently_benchmarked` | A separately implemented reference agrees within tolerance. | External benchmark |

The ladder is monotonic: a later state requires the earlier evidence. Execution alone
promotes nothing. A failed arithmetic check leaves the contract at
`methodologically_eligible` even if an economic review exists.

## Contract fields

- Company and security identity, including whether the ticker mapping is provisional.
- SIC code, business model, sector and the classification basis.
- Supported and prohibited methods.
- Required inputs for the selected method, available inputs and missing inputs.
- Share-count basis and accounting normalization status.
- Information cutoff, model assumptions and their classification.
- Numerical validation results, economic limitations and audit status.

## Method requirements

| Method | Required inputs | Prohibited use |
| --- | --- | --- |
| `unlevered_fcff_dcf` | revenue, shares, net income, cash | banks, insurers, brokers, balance-sheet businesses |
| `residual_income_equity` | equity, net income, shares | substituting for fair-value asset analysis |
| `justified_earnings_equity` | net income, equity, shares, diluted EPS | pure-insurer claims when a service segment is consolidated |

## Why this exists

Phase 9 could report 17 executing DCFs. That number answered "did the arithmetic run",
not "is this the right model". The contract makes the second question explicit and keeps
coverage, eligibility, execution, arithmetic verification and economic support as
separate counts in the API, the report and the UI.
