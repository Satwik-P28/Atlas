# ADR 0031 — Retrieval time is not publication vintage

Status: accepted.

## Context

EIA-930 and GHCN-Daily bulk archives expose observations but not an as-issued historical
publication record for every day. Treating the download time as if it were the historical
publication time, or silently using later data in a 2023 replay, would fabricate availability.

## Decision

Store `availability_time` as the exact archive retrieval instant with
`availability_basis = "archive retrieval instant; not a historical publication vintage"`.
`public_available` queries exclude values not yet retrieved. A cutoff before retrieval returns
a typed `MissingDataError` with the excluded count and correction hint rather than filling with
later data. `published_at` remains null where the source does not expose it.

A replay at 2023 therefore reports `insufficient_evidence`. Replay at the 2026 retrieval
snapshot reproduces the exact retained calculation.

## Consequences

* The flagship cannot claim as-issued historical knowledge or pre-event weather forecasts.
* Users see the limitation in the API, UI and application.
* Future ALFRED/forecast archives can supply real vintages through the same fields.
* No fallback pretends a current bulk archive is point-in-time verified.
