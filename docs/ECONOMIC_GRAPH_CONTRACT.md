# Economic graph contract

Schema: `atlas.economic.graph.v1`.

The graph is a research artifact, not a claim that every economic relationship is observable.
Observed, inferred and hypothetical edges remain distinct and exportable.

## Node contract

Each entity has:

* stable `entity_id`;
* versioned `entity_type`;
* display name and canonical key;
* geography code where applicable;
* evidence `data_class` and `status`;
* source identity;
* valid-from / valid-to dates;
* JSON metadata.

Supported types in the contract are company, legal entity, security, facility, geographic
region, economic sector, infrastructure asset, commodity, economic indicator, government body,
event, contract, dataset and research hypothesis. The implemented fixture uses a justified
subset: region, station infrastructure, commodity, indicators, datasets, hypothesis, company
and facility.

## Edge contract

Every edge exposes:

* stable `edge_id`, from/to entity IDs and names;
* relationship type;
* `source_id`, source name, licence/rights and redistribution;
* observation or claim reference where applicable;
* `valid_from` / `valid_to`;
* confidence or quality status;
* `epistemic_status` (`observed`, `inferred`, `hypothetical`);
* normalized `status`, `current_valid`, `provenance` and `source_evidence`;
* geography and metadata.

Implemented relationship types include `describes_geography`, `station_located_in`,
`geographic_context_for`, `is_affected_by`, `supports_indicator`, `operates_facility`,
`facility_located_in`, `consumes_commodity` and `tested_by`.

## Current graph

| Measure | Value |
|---|---:|
| Entities | 12 |
| Edges | 12 |
| Observed edges | 6 |
| Inferred edges | 1 |
| Hypothetical edges | 5 |
| Claims | 4 |
| Conflicts | 1 |
| Events | 2 |

The only company is named **Hypothetical Texas manufacturer**. It is connected to a
hypothetical facility, regional electricity and ERCOT. Its edges use the non-evidence
assumption source and are not counted as observed facts.

## Query behavior

`GET /api/economic/graph` supports:

* optional as-of filtering on `valid_from`;
* entity lookup with a hard `UnknownEntity` error;
* undirected traversal to bounded depth (1–5);
* entity, edge, claim and conflict inspection;
* counts by epistemic status;
* JSON persistence and export.

`GET /api/economic/panel` supplies time-series inspection. `GET /api/economic/conflicts`
supplies the contradiction view. Graph data is stored in SQLite and reconstructed from the
same observation and source identities as the panel.

## Evidence rules

* An edge without a source is invalid.
* Confidence is a quality input, not a probability of causation.
* A hypothesis is never promoted to observation because it appears in a graph.
* A company’s operating relationship is not inferred from a ticker or a sector average.
* Contractual exposure cannot be fabricated to complete a graph.
* Source rights travel with the edge response.
* A source revision marks dependent analyses stale; unrelated analyses keep their status.

## Limitations

The implemented temporal filter does not yet enforce `valid_to` in the graph query, so callers
must inspect `valid_to` and `current_valid`. There is no graph algorithm beyond bounded
neighbor traversal: no centrality, community detection, path ranking or causal propagation.
There is no facility registry or supplier network. Entity resolution is deterministic canonical
keys, not fuzzy matching. The graph is a narrow evidence index, not a global economic graph.
