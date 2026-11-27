# Known limitations — v0.2.0-beta.2

Every item here is a statement about this release, not about what Atlas is trying to become. Where a
capability is absent it is named as absent, because a misleading "supported" label is worse than a
missing feature.

## Release status

| Limitation | Impact | Status |
|---|---|---|
| Nine Nasdaq and Alpha Vantage files remain reachable in the **development repository's** earlier history | Vendor terms do not permit redistribution; a clone of that repository taken before remediation can recover the blobs | **Not in any artifact** — the wheel, sdist, source snapshot and public candidate contain none. Development repository to be renamed to `Atlas-development` and made private; restricting visibility does not recall existing copies. See [REPOSITORY_MIGRATION.md](REPOSITORY_MIGRATION.md) |
| Publication is not executed | No release page, Pages site or PyPI package exists yet | **Administrative only.** Every engineering and licensing gate passes; the sequence is in [PUBLIC_RELEASE_HANDOVER.md](PUBLIC_RELEASE_HANDOVER.md) |
| No external human usability evaluation | Claimed usability is author-tested only | **NOT RUN**; package prepared, results absent, and no release claim depends on it |

## Product gaps

- **MCP is local, stdio-only and read-only by default.** Fourteen tools exist over the same
  services as the browser; there is no network transport, no resources/prompts, and the single
  mutating tool refuses unless the server was started with `--allow-mutations`. See
  [MCP_GUIDE.md](MCP_GUIDE.md).
- **PDF export is text and vector tables, not charts of the whole memo.** A memo exports as a
  paginated PDF (title page, sections, claim register, disclosures) as well as Markdown, HTML and
  JSON. The PDF carries the scenario bar chart only; there are no embedded page images.
- **Comparison is limited to companies already in the database, and to one period at a time.**
  `/compare` resolves two to six companies through the same concept resolver over a single
  period and reports currency, scale, consolidation-scope, statement-family and coverage
  differences as findings. A blocking finding marks the comparison invalid instead of producing
  a normalised table; there is no peer-set averaging, no cross-period trend comparison and no
  industry index.
- **Command palette covers ten entity classes, not every page action.** Companies, concepts,
  filings, questions, models, strategies, saved research, experiments, workspaces and packages are
  searchable and navigate to real routes; page-local actions (for example "save layout") remain
  keyboard shortcuts rather than palette commands.
- **Market-data onboarding is CSV only, and SEC/FRED ingestion stays on the CLI.**
  `/data` previews and imports CSV bars with a declared licence; Parquet, SEC sync and the FRED /
  ALFRED offline scripts are not reachable from the terminal.
- **No scheduler.** Monitoring is manual: nothing runs when Atlas is not running, and no background
  job claims to.
- **No authentication of any kind.** Single-user local by design. Any multi-user or network
  deployment requires a separate security design that this release does not contain.

## Data and research limits

- **Synthetic price data is the default.** Committed market fixtures are explicitly synthetic. Real
  prices require a user-supplied dataset; Atlas does not bundle licensed market data.
- **Coverage is narrow.** Financial facts are demonstrated on a small set of U.S. issuers (Apple,
  Microsoft, Walmart, Alphabet, IBM, Coca-Cola, 3M, JPMorgan, Goldman Sachs). Broad market coverage is
  not claimed and not measured.
- **Availability is frequently modelled.** For ingested filings the public-release instant is not
  observed; Atlas stores a conservative upper bound derived from EDGAR acceptance plus a publication
  lag, reports precision as `unknown`/`modeled_bound`, and refuses intraday claims built on it.
- **Answer-semantics results are development results.** The 47-question cohort was scored once and is
  now post-holdout development data, not an independent holdout. No human annotators have validated
  the new cohort.
- **Refusals remain.** Two unjustified abstentions (untitled managed-basis reconciliation tables) and
  two resolution failures (note-only evidence, a definitional ambiguity) are documented in
  [FINANCIAL_ANSWER_HARDENING.md](FINANCIAL_ANSWER_HARDENING.md). One citation mismatch remains
  (`Total assets(a)` versus `Total assets`).
- **Certificate semantics are bounded.** `SOURCE_VERIFIED` proves arithmetic consistency and source
  identity. It does not prove the economic interpretation is correct, and Atlas says so in every
  result.
- **Point-in-time reconstruction is bounded by stored data.** Vendor publication vintages are not
  available; price reconstructions are filtered by session date and reported as `unverified` at the
  cutoff rather than claimed as historically published values.

## Engineering limits

- **Windows and macOS are not tested in this environment.** The code avoids platform-specific paths and
  the CLI is pure Python, but only Linux was executed here. Treat other platforms as unverified.
- **Chromium is the certified browser.** The flagship journey is certified on Chromium; Firefox and
  WebKit are attempted on hosted CI runners and their reports are kept with each run, but no
  compatibility claim is made for an engine whose journey has not passed. Responsive checks are
  limited to the viewports the acceptance scripts exercise.
- **Builds are reproducible for one toolchain, and no more.** Wheel and sdist members are stamped at
  the commit time, so two builds of the same commit with the same interpreter, setuptools and zlib
  produce identical bytes. A different toolchain may not. Artifacts are hashed, not signed and not
  attested; verify by installing and running the acceptance commands.
- **The API contract version and package version are independent.** `/api/health` reports both; a
  contract change is a separate decision from a release bump.
- **Large filings are not streamed.** Parsed geometry is cached by document digest; a cold parse of a
  large filing is seconds per document and peak traced memory during profiling reached roughly 700 MB
  for the profiled batch. See [FINANCIAL_ANSWER_HARDENING.md](FINANCIAL_ANSWER_HARDENING.md) for the
  measurement conditions; consumer hardware with little memory should be tested before heavy batch use.

## Phase 10.6 additions

- **Column labels now come from the printed header, and disagreement is refused.** Filers that place
  currency symbols in their own columns or print Change columns between periods used to shift the
  flattened header one column left of the values, so a 2026 amount could carry a "2025" label.
  Periods and labels are read from the printed header slot sequence; a column the header cannot cover
  is reported as `period_column_ambiguous` and no certificate is issued for it, and the answer API
  refuses a citation whose label contradicts its period with 422 `citation_period_conflict`.
- **Chromium certification is 21 of 21.** Both earlier failures were real product defects, not
  selector noise: the frozen row-label column covered every statement value in a narrow panel, and
  saving an unchanged memo returned 422 so the export controls never appeared. Both are fixed. The
  report is `artifacts/browser/phase10_5_chromium.json`.
- **Firefox and WebKit have not passed locally.** The container can install their system libraries but
  has not been certified on them; hosted CI attempts both and keeps the report of each attempt. No
  support claim is made for either engine.
- **Resource behaviour is audited in bounded cases, not fuzzed.** `scripts/audit_resource_limits.py`
  covers malformed HTML, a 4,000-row table, a 31 MB filing (refused at the 24 MiB ingestion limit),
  a 200,000-row CSV, a ZIP bomb and a 200-entry package (both refused), 200 concurrent invalid API
  requests, dropped connections and four concurrent MCP sessions. Peak RSS stayed at 129 MB.
  Expensive model requests were **not** run: no provider is configured.
- **One real filing is certified, not a corpus.** Apple's FY2026 10-K is the live acceptance case;
  filers with very different table shapes are not covered by that evidence.
- **Restricted market data remains reachable in this repository's published history.** See
  [REPOSITORY_EXPOSURE_AUDIT_PHASE10_6.md](REPOSITORY_EXPOSURE_AUDIT_PHASE10_6.md); the clean-history
  candidate and every built artifact contain none of it.
