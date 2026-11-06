# ADR 0011 — Regulatory evidence keeps its legal entity and basis

## Context

SEC consolidated facts and bank Call Reports describe different legal entities. Aggregating
them would double-count assets and equity.

## Decision

Store regulatory observations with an explicit entity, certificate, form and consolidation
basis. Link parent and subsidiary for research but never sum them. Use the consolidated parent
for per-share valuation and subsidiary evidence for capital, credit and margin context.

## Consequences

Models can show real regulatory evidence without pretending it is consolidated. Some useful
parent-level metrics, such as tangible book per share, remain unavailable until goodwill is
mapped from SEC facts.
