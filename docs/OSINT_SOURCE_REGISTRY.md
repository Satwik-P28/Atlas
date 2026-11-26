# OSINT source registry

Status: a minimal deterministic registry for the flagship study. It is not a general web
crawler and does not claim broad OSINT coverage.

## Registered source contract

Each source declares provider, official dataset, source type, geography, temporal coverage,
observation time, publication time where known, retrieval time, revision availability, update
frequency, units, quality, rights, redistribution, rate limits, provenance, retention and
archival rules.

The runtime registry stores `source_id`, name, kind, homepage, licence, redistribution and
notes. The fixture manifest adds file URLs, SHA-256 hashes, transformations, limitations and
station metadata.

## Implemented registry

### EIA-930

* Provider: U.S. Energy Information Administration.
* Dataset: Form EIA-930 hourly balancing-authority operations, six-month balance files.
* Coverage: ERCO, 2023 hourly demand; current bulk archive.
* Units: MW for demand; daily aggregates add MWh.
* Time: `Data Date` treated as local operating day.
* Rights: U.S. Government public domain; redistribution permitted.
* Rate limits: no API key or live calls in the committed build; files downloaded once.
* Limitation: balanced/submitted data can reflect later operator corrections. The archive is
  not an as-issued historical vintage and is not settlement-grade metering.

### NOAA GHCN-Daily

* Provider: NOAA National Centers for Environmental Information.
* Dataset: GHCN-Daily station files.
* Stations: `USW00013960` (Dallas/Fort Worth International, primary) and `USW00003971`
  (Dallas Redbird, comparison).
* Variables used: TMAX, TMIN; daily mean derived; precipitation retained where present.
* Units: tenths of °C in source, converted to °C.
* Rights: U.S. Government public domain; redistribution permitted.
* Limitation: quality-controlled archive values are not a forecast; a point station is not
  an area-weighted ERCOT temperature; exact historical availability is not established.

### Atlas assumption registry

`atlas-assumption` is not evidence. It labels the hypothetical company, facility, demand
hypothesis and contractual exposure. The graph and API treat its edges as hypothetical, with
confidence not interpreted as probability.

## Extraction and reconciliation actually implemented

* Deterministic fixture parsing from documented CSV columns.
* Stable claim identities from subject, predicate, value and source.
* Observation-time and retrieval-time normalization.
* Entity records with canonical keys and geography.
* Claim extraction for daily maximum temperature and the weather-demand hypothesis.
* Contradiction detection for two station observations of the same metro-area subject.
* Source-quality and rights warnings.
* Research revision records; no destructive update.

## Not implemented

* HTML/PDF document collection and reading.
* News de-duplication or syndication clustering.
* General entity recognition or entity resolution.
* Geographic geocoding beyond documented station coordinates.
* LLM-assisted extraction.
* GDELT ingestion, mention counts or event severity scoring.
* Any automated allegation, wrongdoing or culpability labeling.

A large number of repeated articles would not be treated as independent confirmation. No
mention count is used as an economic severity measure.

## Security and rights

Retrieved text is untrusted. It cannot alter permissions, file paths, model configuration or
financial calculations. External source URLs are stored as metadata only; the runtime does
not fetch arbitrary URLs. Documents and extracted claims stay behind the evidence and
authorization boundary. No private or personal location data is ingested. Public-domain
attribution and source URLs are retained in derived artifacts.

## Future sources, not integrated

FRED/ALFRED, SEC filing text, procurement records, infrastructure datasets, GDELT, trade and
shipping, regulation, patents, hazards, demographics and real estate. Each would need a
declared rights/timing contract, rate-limit policy and independent validation before being
counted as a capability.
