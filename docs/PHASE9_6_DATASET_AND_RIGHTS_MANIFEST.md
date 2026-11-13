# Phase 9.6 — Dataset and Rights Manifest

## Evaluation dataset

| Field | Value |
| --- | --- |
| Dataset | `PatronusAI/financebench` (Hugging Face datasets-server) |
| Subset used | `OPEN_SOURCE` (150 rows) |
| License | `cc-by-nc-4.0` |
| Atlas usage | evaluation only, no redistribution |
| Questions scored | 112 (10-K targets) |
| Questions excluded | 38, each with a recorded reason |
| Question-set SHA-256 | stored in `artifacts/phase9_6_evaluation.json` |

Rows are consumed from a local working copy and are **not** committed. No question text, reference
answer or evidence string from the dataset appears in this repository, in the evaluation artifact
or in the documentation; the artifact stores only derived per-question metrics keyed by
`financebench_id`, plus target accessions that are public EDGAR identifiers.

**Rights position.** CC-BY-NC-4.0 permits non-commercial evaluation. It does not grant rights to
redistribute the underlying filings, and Atlas does not: the corpus is fetched from SEC EDGAR at
build time by `scripts/phase9_6_corpus.py` and stored in `var/phase9_6.db`, which is untracked.
Any commercial distribution, benchmark service or public leaderboard built on this dataset needs
a separate rights review.

## Source corpus

| Field | Value |
| --- | --- |
| Documents | 64 10-K filings, 32 issuers (one per fiscal year) |
| Passages | 112,484 |
| Tables | 11,851 |
| Source bytes | 303,025,449 |
| Failed ingestions | 0 |
| Excluded documents | 18 (outside ingested scope) |
| Manifest | `artifacts/phase9_6_corpus_manifest.json` |
| Database | `var/phase9_6.db` (git-ignored) |

Issuer identity is an explicit 32-entry table in `src/atlas/research/financebench.py`, verified
against SEC issuer names. Fuzzy string matching was tested and rejected: it mapped Amazon→AAON,
Verizon→Veritone and CVS→VSEE, which would silently attach questions to the wrong company.

## SEC access

* User agent is required from `ATLAS_SEC_USER_AGENT`; `sec_user_agent()` raises
  `SEC_USER_AGENT_UNSET` rather than shipping a placeholder contact address.
* Requests are throttled (`SEC_MIN_INTERVAL = 0.15`) and retried with backoff.
* Responses are gzip-sniffed by magic bytes, because SEC returns gzip even when
  `Accept-Encoding: identity` is sent.
* Historical submissions are read from the paged `CIK##########-submissions-00N.json` files; the
  first page alone does not reach 2015–2019 for several issuers.

## Redistribution boundaries

| Artifact | Committed? | Reason |
| --- | --- | --- |
| `artifacts/phase9_6_evaluation.json` | yes | derived metrics only |
| `artifacts/phase9_6_corpus_manifest.json` | yes | identifiers, hashes, counts |
| `artifacts/phase9_6_case_study.json` | yes | short public-filing excerpts with hashes |
| `var/phase9_6.db` | no | full third-party source bytes |
| FinanceBench rows | no | CC-BY-NC-4.0 evaluation material |
