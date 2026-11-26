# Strategy contract — `atlas.strategy.v1`

A strategy is stored as an immutable `atlas.research_object.v1` object with
`kind: "strategy"`. The same document is validated by the API and the simulator.

```json
{
  "schema_version": "atlas.strategy.v1",
  "name": "Trend following · IBM",
  "version": "1.0.0",
  "description": "Hold when the 20-session mean exceeds the 100-session mean.",
  "universe": {"instruments": [{"security_id": "SEC-…", "mic": "XNYS"}]},
  "features": [
    {"name": "close", "kind": "price", "window": 1},
    {"name": "sma20", "kind": "sma", "window": 20}
  ],
  "signal": {"kind": "sma_cross", "fast": 20, "slow": 100},
  "decision_frequency": "daily",
  "rebalance": "daily",
  "execution": {
    "signal_at": "close",
    "fill_at": "next_open",
    "commission_bps": 2,
    "slippage_bps": 5
  },
  "benchmark": {"kind": "buy_hold"},
  "initial_capital": 100000,
  "constraints": {"long_only": true, "max_position": 1.0},
  "risk_free_rate": 0.02,
  "source_ids": ["alphavantage"]
}
```

## Supported signals

| Kind | Parameters | Behavior |
|---|---|---|
| `buy_hold` | none | target 100% invested |
| `sma_cross` | `fast`, `slow` | target 1 when fast SMA > slow SMA, else 0 |
| `momentum` | `fast` (lookback), `threshold` | target 1 when lookback return > threshold |
| `model` | `model_spec`, `input_map`, `output` | evaluate a typed `atlas.model.v1` model |

A custom signal uses the shared compiler and operator registry:

```json
{
  "kind": "model",
  "model_spec": {
    "schema_version": "atlas.model.v1",
    "name": "Price / SMA signal",
    "interface": "equation",
    "inputs": {"close": "Price[USD]", "sma": "Price[USD]"},
    "equations": [{"name": "signal", "expr": "close / sma - 1"}],
    "outputs": ["signal"]
  },
  "input_map": {"close": "close", "sma": "sma20"},
  "output": "signal"
}
```

## Rejected declarations

* More than one instrument (this release supports one).
* Shorting or `long_only: false`.
* Any fill other than `next_open`; any signal other than `close`.
* Missing or duplicate feature names.
* Unknown operators, model inputs, model outputs or feature references.
* Unsupported frequency (only daily, weekly and monthly are accepted).
* Changing costs/parameters while reusing an existing name and version; the registry
  raises rather than silently ignoring the new document.

## Versioning

`name` + semver `version` identify an immutable research object. A changed strategy must
use a new version or a new name. The content hash, model fingerprint and result
fingerprint are retained with the run and experiment.
