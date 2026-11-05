# ADR 0038: declarative domain packs

**Status:** accepted (Phase 8)

## Context

Domain packs could accelerate research, but a pack that registers code or rewrites operators would
become a second platform with an unaudited execution surface.

## Decision

A pack is a JSON declaration with metadata, source/right declarations, compatibility, test vectors,
limitations and references to `.atlas` packages. It may request only known declarative
capabilities. Its embedded packages are fully validated before any write. Installation is one
transaction; uninstall removes pack metadata but retains applications and research objects.
Unknown or executable content is rejected.

## Consequences

Packs cannot ship custom algorithms in this phase. The real `atlas.energy-research` pack installs
the weather-demand application through the ordinary package lifecycle. A future executable pack
contract must extend the isolation decision in ADR 0036, not silently weaken it.
