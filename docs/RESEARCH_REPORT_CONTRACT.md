# Research report contract

Schema: `atlas.equity_research.report.v1` (metadata), `atlas.equity_research.v1` (analysis
envelope), `atlas.equity_research.dcf_audit.v1` (audit), `atlas.equity_research.package.v1`
(package result).

## Guarantees

- **Deterministic.** The same database, cutoff, assumptions and mode produce the same
  Markdown and the same SHA-256. No LLM, news feed, clock or random seed is involved.
- **Source-linked.** Every metric in the report traces to an evidence id. The report itself
  cites SEC accessions through the packaged financial snapshot and X-Ray.
- **Explicit gaps.** Missing concepts and missing latest-period metrics are listed; they are
  never rendered as zero.
- **Two-level verdict.** The report states financial coverage separately from valuation
  eligibility, execution, arithmetic audit and economic support.
- **Hash integrity.** `metadata.report_sha256` is the SHA-256 of the exact report string, and
  the package embeds that report with the same digest in its manifest.
- **Unsigned.** The package has no signature; the hash proves integrity, not publisher
  identity.

## Required sections

1. Title, ticker, CIK, information cutoff, mode, no-LLM statement.
2. Research question.
3. Company identity and source-limited context (no invented narrative).
4. Data coverage (evidence, annual periods, filings, market observations).
5. Historical financial results as a per-period table.
6. Financial reconciliation and quality checks with expected, actual and status.
7. Valuation methodology and eligibility, including rejection reasons and the required
   remedy.
8. Valuation outputs, assumptions and provenance, scenarios, sensitivity, optional reverse
   DCF.
9. Share denominator basis and limitation.
10. Independent DCF component audit table and verdict.
11. Historical availability and missing information.
12. Risks visible in the reported data.
13. Peer context without a curated-industry claim.
14. Findings and audit verdict.
15. Reproduction (selection policy, compiler, source revision).

## Prohibited content

- A qualitative business description, competitive position or management narrative without
  a source document.
- A target price, rating or recommendation.
- A comparable-company multiple or synthetic quote when prices are absent.
- A valuation for a financial institution using the generic DCF.
- A claim of institutional quality or validated usability.
