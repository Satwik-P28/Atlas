# ADR 0036: no untrusted executable application extensions

**Status:** accepted (Phase 8)

## Context

A plugin API would let third parties add models and views, but a Python subprocess or virtualenv is
not a security sandbox. Shipping an unisolated extension runtime would make package installation
equivalent to arbitrary code execution.

## Decision

Applications are declarative. Execution dispatches only to the existing `atlas.fec.model.v1` and
`atlas.economic.weather_demand.v1` runtimes. Packages cannot request filesystem, network,
credential, process or cross-user capabilities. The package scanner rejects executable-looking
keys and file types. A future extension requires an isolated worker, resource quotas, explicit
capability grants, audit, revocation and supply-chain verification.

## Consequences

Legitimate third-party algorithms cannot ship in Phase 8. That is an intentional capability
reduction. The platform remains reviewable and the economic/FEC engines stay authoritative. Real
estate, OT/SCADA and arbitrary provider adapters are not implemented through a code back door.
