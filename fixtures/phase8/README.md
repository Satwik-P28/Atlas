# Phase 8 fixtures

`flagship_weather_demand.atlas` is built from the repository's real 2023 EIA-930
and NOAA GHCN-Daily fixtures through the ordinary Economic Lab and package code.
It is unsigned. The SHA-256 in `energy_research_pack.json` proves byte integrity,
not publisher identity.

- run: `ERUN-ac92ae9ffef03de2`
- scenario: `ESCN-9d3326c5354c4a5b`
- package: `APKG-a992e7f25f718a0eb7c8`
- package SHA-256: `92ab1bf753438a0f534a080697abca9c638da11521e13c1dc43700883c82227b`
- built at: `2026-11-05T22:03:29Z` (the pinned artifact, not a live rebuild)
- limitations: test RMSE 2,956.58 MW, test R² -0.8935, positive bias, unidentified causality,
  hypothetical manufacturer exposure, current archive rather than historical vintage.
