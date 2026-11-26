# Technical article draft — "A financial answer should be a citation"

*Draft for a personal blog or a technical publication. Every number below is measured in the release
environment and reproducible from the repository.*

## The claim

An answer to a financial question is a *citation plus a computation*, not a sentence. If the system
cannot produce the cell and the arithmetic, it has not answered; it has guessed fluently.

## Four ambiguity axes

1. **Statement identity.** "Net sales" in a segment table is not consolidated net sales.
2. **Filing vintage.** Original versus amended, current versus superseded.
3. **Unit and scale.** Thousands versus millions; per-share versus total.
4. **Availability.** Filed, accepted, publicly readable — three different instants.

Atlas models each axis explicitly and refuses when more than one candidate survives. This is
unpopular in demos and correct in research.

## Architecture in one paragraph

A filing is parsed into text units and tables with character offsets and SHA-256 digests. A closed
vocabulary of concepts resolves a question to a cell by phrase rules, scope rules and a filing whose
own period is the requested year. Accepted arithmetic compiles to an expression over exact fractions;
an independent verifier re-reads pinned bytes and recomputes. Everything is stored in one SQLite file
and served over loopback; the same evidence is exposed through HTTP, a CLI and an MCP server.

## What the release run showed

- Apple FY2026 10-K: 1.65 MB → 60 tables, 728 units, 0.2 s ingest from local bytes; total net sales
  478,834; certificate verified; identical reproduction on a second installation.
- Synthetic offline acceptance: 30/30 steps, including PDF (34/34 numeric claims found in the
  extracted text) and MCP agreement with the HTTP answer.
- Official `mcp` SDK interop: 14 tools, structured content, typed refusal for a period with no
  evidence, `authorization_required` for a mutation in read-only mode.
- Demo-workload latencies from the previous environment (p50/p95): palette search 6.5/8.3 ms,
  statements 182/212 ms, certificate 9.8/23.7 ms, DCF 22.0/51.0 ms, PDF 19.1/32.8 ms, MCP 5.5/14.4 ms.

## Two bugs the process found, and why they matter

**A wrong column label on `$`-separated tables.** Flattening made a 2026 value cite "2025". The
number and the resolved period were right; the citation label was not. The fix is not a cleverer
guess: it is a flag (`ambiguous_column_label`) so a reader knows which part of the citation is
machine-verified.

**A blank page after "Build certificate".** The UI stored the certificate response where it expected
a resolution, and the next render dereferenced a field the certificate does not have. A browser
certification run caught it; no API test could have.

## What is not claimed

No generative model in the answer path; no vendor market data; no institutional readiness; no
independent human evaluation yet. A certificate is a fingerprint, not a signature, and it proves
consistency with the cited bytes, not economic interpretation.

## Reproduce

```bash
python -m pytest tests/test_mcp_sdk_interop.py
python scripts/accept_phase10_4.py
ATLAS_SEC_USER_AGENT="You you@example.org" python scripts/accept_real_filing_phase10_5.py
```
