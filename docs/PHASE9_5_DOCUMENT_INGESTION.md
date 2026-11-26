# Phase 9.5 — document ingestion

## 1. Pipeline

```
SEC submissions API (data.sec.gov)        discovery: form type, acceptance time, period, primary doc
        │
        ▼
primary document URL (sec.gov/Archives)   one User-Agent, explicit identity encoding
        │
        ▼
deterministic HTML extraction            headings → sections, paragraphs, tables (rows/cells)
        │
        ▼
normalisation                            entities decoded, whitespace collapsed, spans computed
        │
        ▼
content-addressed storage                sha256 of the bytes, immutable accession, counts
        │
        ▼
FTS5 index                               body + heading + section path, ids unindexed
```

Command:

```bash
python scripts/phase9_5_ingest.py --db var/phase9_5.db --cik 0000320193 --forms 10-K,10-Q --limit 2
python scripts/phase9_5_ingest.py --db var/phase9_5.db --cik 0000019617 --forms 10-K,10-Q --limit 1
```

## 2. What was ingested for this phase

| Issuer | Documents | Passages | Tables | Source bytes |
| --- | --- | --- | --- | --- |
| Apple (CIK 320193) | 2 × 10-K, 2 × 10-Q | 1,616 | 152 | 4,434,428 |
| JPMorgan (CIK 19617) | 1 × 10-K, 1 × 10-Q | 4,935 | 546 | 23,054,709 |
| **Total** | **6** | **6,551** | **698** | **27,489,137** |

Every document carries an SEC acceptance timestamp, so `availability_precision = exact`.
Ingestion is idempotent per accession: the same bytes return the existing document, different
bytes raise `ValidationError`.

## 3. Two real defects the pipeline exposed

1. **Gzip payload read as text.** SEC returned `Content-Encoding: gzip` despite an identity
   request, so the first 10-K parsed as binary and produced **one** passage. Fixed by sniffing the
   gzip magic bytes in `_decoded`. This is why the first run reported `unit_count: 1`.
2. **Void tags swallowed the document.** `meta` and `link` are in the skip set but never emit an
   end tag, so skip depth stayed above zero and everything after `<meta charset>` was discarded.
   Fixed with an explicit `VOID_TAGS` set. The same run reported one passage for a 117 KB file.

Both bugs would have passed a "documents ingested > 0" test. They were found because the
`unit_count` and the missing "customer" term were inspected, not because a request returned 200.

## 4. Extraction rules

- Headings (`h1`–`h6`) and `Item N.` lines start a section; the section path is the most recent
  heading, capped at 240 characters.
- Block-level end tags and a new block start flush the current text buffer, so paragraphs do not
  merge across `div`/`p` boundaries.
- Tables become one unit whose body is `cell | cell | cell` lines with an optional caption line;
  the structured rows are stored separately in `knowledge_table`, together with detected period
  headers (four-digit years) and footnote-like rows.
- Inline XBRL numeric tags are **not** parsed into facts. Atlas already receives structured facts
  through its SEC company-facts path; extracting them twice would create a second fact pipeline.
- Text is normalised (`&nbsp;`, CR, repeated spaces) before spans are computed, so spans always
  index the same normalised text that is stored.

## 5. Amendments

`form_type` ending in `/A` sets `is_amendment`, and the driver links `amends_accession` to the most
recent earlier non-amendment filing of the same issuer. Amendments are indexed as separate
documents; they are never merged into the original, so a historical query cannot see a correction
that did not exist at its cutoff.

## 6. Rights

Primary SEC filings are archived as `public_domain` with the note that exhibits may carry
third-party rights. Only primary documents are stored — no exhibits are archived, and the
archive status reports `local_only` retention. The rights classifier is not bypassed: an
unrecognised class fails closed, and `restricted` documents produce
`restricted_source` in claim verification with `export_allowed: false`.

This is a deliberate, documented position, not a legal opinion: an operator deploying Atlas
commercially must review the redistribution question for each source independently.

## 7. Limits

- HTML only. PDF exhibits, image-based filings and older plain-text filings are not parsed.
- No OCR, no table-layout inference beyond row/cell order, no footnote attachment to specific
  cells (footnotes are captured as text).
- One primary document per accession; a filing whose content lives in exhibits is incomplete.
- `MAX_DOCUMENT_BYTES = 24 MB`; larger documents are rejected rather than truncated.
- 27.5 MB of source text supports 6 documents. A production corpus needs external storage or
  compression; SQLite remains adequate for research-scale local use.

## 8. Reproduce

```bash
cp var/phase9_export.db var/phase9_5.db
python -m atlas.cli --db var/phase9_5.db migrate      # schema 13 → 14
python scripts/phase9_5_ingest.py --db var/phase9_5.db --cik 0000320193 --forms 10-K,10-Q --limit 2
python scripts/phase9_5_ingest.py --db var/phase9_5.db --cik 0000019617 --forms 10-K,10-Q --limit 1
```
