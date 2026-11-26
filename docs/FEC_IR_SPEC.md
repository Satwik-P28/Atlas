# FEC IR specification (`atlas.fec.ir.v1`)

## Model document (`atlas.model.v1`)

```json
{
  "schema_version": "atlas.model.v1",
  "name": "Unlevered DCF",
  "version": "1.0.0",
  "interface": "graph",
  "inputs": [{"name": "revenue", "type": "Money[USD]", "required": true}],
  "nodes": [{"id": "growth", "op": "forecast_series",
             "inputs": ["revenue", "revenue_growth"],
             "params": {"periods": 5}}],
  "outputs": {"value_per_share": "per_share"},
  "as_of": "2024-11-01T16:05:00Z",
  "mode": "public_available",
  "evidence_ids": [],
  "assumptions": []
}
```

Equation interface adds `equations: [{"name","expr"}]` and omits `nodes`; the compiler
translates equations into the same node graph.

## Typed IR (`CompiledModel`)

- `nodes`: id → `{op, inputs, params, type, label}`
- `order`: topological order of output ancestors
- `outputs`: output name → node id
- `inputs`: name → `FinType`
- `fingerprint`: SHA-256 of canonical spec + compiler version + all operator versions
- `plan`: ordered `{position, id, op, inputs, type, operator_version}`
- `diagnostics`: structured `{code, message, node, hint, ...}`

## Cache key

`SHA-256(fingerprint, node id, operator, operator version, params, canonical input
values, precision)`. Input values are mandatory: omitting them would silently reuse a
stale result after a source change. Model metadata (`as_of`, `mode`, evidence ids) is
included in the model fingerprint through the canonical spec.

## Run manifest

`run_id`, fingerprint, model/version, compiler and operator versions, `as_of`, mode,
canonical inputs and their hash, evidence ids, assumptions, node count, cache hits/misses,
duration and creation time. Runs are stored in `model_run`; node results in
`model_node_cache`.
