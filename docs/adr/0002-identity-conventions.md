# ADR 0002 — Identity conventions: issuers, securities, listings, tickers

- **Status**: accepted (Phase 1)
- **Date**: 2026-11-03

## Context

The specification's hardest identity statement is: **a ticker is not a permanent
security identifier.** Real markets contain one issuer with several share classes,
ticker changes, ticker reuse, multiple listings in different currencies, delistings,
mergers, spin-offs and identifiers that conflict across vendors. A system that keys
securities by symbol corrupts history the first time a symbol is reused, and the
corruption is invisible until a backtest uses the wrong company's prices.

## Decision

Four explicit levels, each with its own identifier:

1. **Issuer** — a legal entity. Anchored on the SEC CIK (`ISS-CIK0000320193`) when the
   entity is a registrant; otherwise a digested canonical name+domicile (`ISS-E…`).
2. **Security** — a tradable instrument from exactly one issuer, distinguished by a
   canonicalised share-class key (`common`, `class_a`, `class_b`, …). Id is
   `uuid5(issuer_id, class_key)`; the ticker is **never** an input.
3. **Listing** — `(security, venue MIC)` effective over `valid_from..valid_to`.
4. **Ticker assignment** — `(listing, symbol)` effective over `valid_from..valid_to`,
   carrying `confidence` (0–1) and `status` (`confirmed | probable | unverified | retracted`).

Rules:

* Identifier assignments (`CIK`, `ISIN`, `FIGI`, `CUSIP`, vendor ids) are also
  time-bounded rows with confidence, status and a licence note.
* Resolution returns an inspectable verdict (`confirmed | probable | ambiguous | none`)
  with reasoning. Simultaneous claims by two securities are `ambiguous`; nothing is
  auto-selected and `require_single()` raises.
* Ticker reuse is normal data, not corruption: two securities hold non-overlapping
  windows for the same symbol and resolve differently by `as_of`. Between owners, the
  symbol resolves to nothing.
* A ticker change closes the old assignment on the effective eve; it never rewrites it.
* Delisting closes windows without deleting them, so historical queries still resolve.
* SEC cover-page tickers are attached with `probable` confidence for a single-ticker
  issuer and `unverified` for multi-ticker issuers, because the SEC payload does not map
  symbols to share classes. This is recorded as a limitation rather than guessed away.

## Consequences

* Observations and evidence are keyed by `security_id`, so a ticker change never
  re-attaches history to a different company.
* Tests cover ticker change, reuse, gaps, simultaneous claims, multi-class issuers,
  delistings and conflicting ISINs from different sources.
* The master cannot silently absorb a new identifier scheme: adding one requires
  registering the scheme and a licence note, which is a deliberate review point.
* Cost: ingestion must know the share class to create a security. Where it does not, the
  record is explicitly provisional — the honest option.

## Alternatives considered

* Ticker as key, with history tables: rejected — every consumer would need to remember
  to use the history table, and one forgetful join reintroduces the bug.
* Composite `(ticker, exchange)` identity: rejected — still fails on ticker change and
  reuse, and conflates venue with instrument.
* Hash of all known identifiers: rejected — identifiers arrive over time, so the id
  would change, breaking immutability.
