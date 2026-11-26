# Phase 9.6.4 — XBRL Reconciliation

## Status: not implemented (documented blocker)

The corpus schema exposes only `is_xbrl` / `is_inline_xbrl` flags on documents; there is no fact
table with concept, context, unit and accession columns. SEC `companyfacts` alignment was not
implemented in this phase.

Consequences:

- Concept identity remains lexical plus statement/segment context, not XBRL-verified.
- HTML/XBRL disagreements cannot be surfaced because no XBRL side exists in the store.
- XBRL is never used as a silent replacement for source localization, because it is not used at
  all.

The 9.6.3 artifact's `xbrl_status: unavailable: no XBRL fact table in this corpus` remains accurate
for the current corpus. Implementing a bounded, rights-compliant companyfacts adapter is the next
scientific step and is a release blocker for any claim of XBRL corroboration.
