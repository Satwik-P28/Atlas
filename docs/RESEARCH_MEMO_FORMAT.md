# Research memo format

Contract: `atlas.research_memo.v1` (`src/atlas/research/memo.py`). Persisted as a
`research_object` of kind `memo` using the existing versioned store.

## One object, several views

The memo is authoritative. Markdown, HTML and JSON are renders of the same claim register, so
a screen, a downloaded report and a machine-readable manifest cannot disagree about a number.
No export format recomputes a value.

## Object layout

| Field | Content |
| --- | --- |
| `schema`, `memo_version` | `atlas.research_memo.v1`, `1.0.0`. |
| `memo_id` | `RMO-` + first 16 hex of the content hash. Derived. |
| `name` | Human name; the saved research object uses it. |
| `workspace_id` | The research workspace the memo was created from, or `null`. |
| `issuer` | Issuer id, legal name, CIK, SIC, ticker, business model, valuation method. |
| `cutoff`, `mode` | Information cutoff and availability mode. |
| `objective` | The research question, stated once. |
| `claims` | The verified claim register (see the claim contract). |
| `sections` | 20 ordered sections, each with claim ids, items and notes. |
| `integrity` | Four independent dimensions, failures and outcome counts. |
| `citations` | Resolved evidence citations, the market pin, and model citations. |
| `rights` | Redistributability decision and blocked sources. |
| `manifest` | Evidence dependencies, observation pins, model fingerprints, assumptions. |
| `content_hash` | SHA-256 over everything except derived fields. |

## Content hash

`memo_hash()` hashes a canonical JSON encoding after removing `content_hash`, `generated_at`,
`memo_id`, each claim's `research_object_id`, and the manifest's own `content_hash`. Those are
derived, so the hash is stable across a rebuild and can be recomputed by a reviewer from the
published document.

## Sections

Identity and version · issuer and security · information cutoff · research objective ·
financial summary · historical analysis · valuation methodology · model assumptions ·
scenarios and sensitivity · numerical validation · market comparison · analyst thesis ·
risks and counterarguments · evidence coverage · unresolved contradictions · source
limitations · research integrity · references · reproduction manifest · export and rights.

Every section is generated from the shared register. There is no second calculation path for
"sections seen on screen" versus "sections in the download".

## Exports

| Format | Media type | Notes |
| --- | --- | --- |
| `markdown` | `text/markdown` | Tables and claim register; deterministic, byte-stable. |
| `html` | `text/html` | Self-contained with inline CSS; every dynamic value escaped with `html.escape(..., quote=True)`. |
| `json` | `application/json` | The manifest plus the full memo, sorted keys. |

Each export carries a manifest with the format, the SHA-256 of the exported bytes, the memo
content hash, the object id and version, the evidence dependencies, the observation pins, the
model fingerprints, the integrity outcomes and the rights decision.
`verify_export()` recomputes the digest, so a tampered manifest is detectable.

PDF is **not** offered. A browser print-to-PDF path was not implemented or verified in this
checkpoint, and shipping an unverified binary renderer would compromise determinism.

## Escaping and safety

Source text and analyst text are escaped in HTML; no template evaluates content. A `<script>`
in a company name renders as text. The export refuses to run when a cited source is not
redistributable, so a restricted vendor series cannot be embedded in a distributable report.

## Versioning

`ResearchMemoService.save()` writes an immutable `research_object` version. Editing produces a
**new** version; the old one stays retrievable and reproducible. `compare()` reports added
claims, removed claims and changed claims (value, statement, evidence), plus assumption and
model-fingerprint differences. Nothing overwrites the old memo because a filing or a provider
revision exists.

## Determinism

The memo excludes wall-clock timestamps from its hash, drops runtime timings from the model
audit before packaging, and sorts every id list. Two builds of the same issuer at the same
cutoff and assumptions produce the same `content_hash`.
