# Show HN draft

**Title (78 chars):** `Show HN: Atlas – financial answers with the exact source cell and a check`

**URL:** the landing page (`docs/launch/index.html`, published statically — not a live API).

**Body:**

I built Atlas because I kept hitting the same wall: a financial figure in a dashboard or an LLM
answer tells you *what* the number is, never whether it is the right number for the question. The
same label appears in consolidated and segment statements, in original and amended filings, in
thousands or millions, and with different meanings across filers.

Atlas resolves a question to exactly one cell of one parsed filing: document, table, unit, row,
column, raw text, scale, currency. It then compiles the arithmetic to exact fractions, verifies the
result against pinned document bytes, and reports a fingerprint — explicitly *not* a signature. When
the concept is ambiguous or the evidence is missing, it refuses with a code, the candidates and the
reason. A refusal is a first-class result.

What is actually measured in the release:

- A real 10-K (Apple, FY2026, 1.65 MB) parses into 60 tables and 728 text units in 0.2 s; the
  question "total net sales, FY2026" answers 478,834 with a verified certificate, and reproduces
  identically on a second installation (same value, same source-table hash).
- A 30-step offline acceptance on a bundled synthetic 10-K covers answer → certificate → verify →
  valuation → scenario → comparison → memo → PDF → MCP → reproduction.
- The MCP server (14 tools) works with the official `mcp` Python SDK: initialize, discovery,
  structured content, typed refusals, and a read-only refusal for mutations.
- Everything runs locally: SQLite, loopback API, bundled frontend, no account, no LLM calls.

It is deliberately not: a market-data terminal (no vendor prices bundled), a forecasting product,
multi-user, or proof that an interpretation is economically correct. Independent human evaluation
and external usability testing have not been run — this is an experimental public preview.

Happy to be told the design is wrong. The part I would most like attacked is the resolution policy:
should a segment total ever be allowed to answer a consolidated question with a warning, rather than
being refused?

**First comment (from the author, immediately):**

Three specifics that HN usually asks:

1. **Why not XBRL?** Atlas parses the filing's own tables because that is what a human reads, and
   because the citation has to survive as a cell. XBRL facts are available alongside and are used
   for cross-checks, not as the citation of record.
2. **Why is availability modelled?** SEC acceptance timestamps are not public-release timestamps.
   Atlas reports precision (`unknown`, `date`, exact) and labels modelled bounds instead of
   pretending to know.
3. **Does it hallucinate?** There is no generative model in the answer path. The failure mode is
   refusal or a wrong citation, and citations are machine-checkable — which is why a real-filing run
   surfaced an ambiguous column label on tables that put `$` in its own column.

Do not claim: Bloomberg equivalence, institutional production readiness, guaranteed returns.
