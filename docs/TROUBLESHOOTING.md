# Troubleshooting

Diagnose from the inside out: `atlas doctor` first, then the specific component.

## Installation

**`atlas: command not found` after install.** The virtualenv is not active, or pip installed into a
different interpreter. Activate `.venv` and run `python -m pip show atlas-quant`, then
`.venv/bin/atlas doctor` (`.venv\Scripts\atlas.exe` on Windows).

**ImportError for `fastapi`, `uvicorn`, `scipy`, `osqp` or `clarabel`.** These are optional extras.
Install what you need:

```bash
pip install "atlas_quant-0.2.0b1-py3-none-any.whl[terminal]"   # HTTP API and UI
pip install -e ".[dev,terminal,learning,columnar,optimization]" # source tree, everything
```

The decision tests import their reference solvers lazily, so a missing solver makes a cross-check
unavailable rather than failing collection — always check that `osqp` and `clarabel` are present when
you intend to rely on the decision layer's verification.

**`atlas demo` cannot find fixtures.** A source checkout needs `fixtures/`; an installed wheel needs the
fixtures staged at build time. Reinstall the release artifact. To point at another tree:
`atlas demo --fixtures /path/to/fixtures`.

## Database

**`atlas doctor` reports `attention_required`.** Read the JSON: `integrity` other than `ok` means file
corruption (restore from backup); `foreign_key_violations > 0` means a broken relation (do not write
further, restore); `schema_version < supported_schema` means migrate.

**`database schema is newer than this Atlas build`.** You are running an older build against a newer
database. Upgrade Atlas; do not downgrade the database.

**Migration failed midway.** `atlas migrate` snapshots before migrating. Restore the snapshot the
command reports, fix the cause (usually disk space or a concurrent writer), and retry. Never edit schema
tables by hand.

**`database is locked`.** Another process holds a write transaction: a running `atlas serve` instance or
a stuck ingest. Stop the other process rather than deleting `-wal`/`-shm` files.

## SEC ingestion

**403 or repeated refusals.** Set an identifying `ATLAS_SEC_USER_AGENT` (`App/version contact@domain`),
stay within SEC fair-access limits, and retry later. Atlas refuses unsafe redirects rather than
following them silently.

**A filing is present but has no text.** Only primary documents that were archived can be quoted.
`original_document_not_ingested` means the locator is known and the bytes are not; Atlas will not invent
an excerpt.

**A document is refused as not available at the cutoff.** The stored availability is later than your
cutoff. Either the filing really was published after that instant, or only a date was known (pinned to
the end of that UTC day). In the second case, the answer is genuinely uncertain at intraday precision.

## Answers and certificates

**A question is refused with `definitional_ambiguity`.** Two definitions fit (for example net income
versus net income attributable to the parent). Add the concept that names the definition you want; Atlas
will not choose for you.

**Refused with `scope_mismatch` or `mixed_reporting_scope`.** The operands are consolidated and segment
figures mixed, or the statement selected is not the one your scope requires. Ask for the consolidated
statement explicitly or supply operands from one scope.

**`INVALID` on a certificate you did not modify.** Check that the manifest and snapshots are the ones the
certificate was issued against, and that the file was not reformatted. A certificate fingerprint is a
pure function of its body; reformatting JSON changes nothing, editing any bound field changes everything.

**`ARITHMETIC_VERIFIED` instead of `SOURCE_VERIFIED`.** No trusted evidence was supplied. Pass
`--manifest` and `--snapshots` pointing at the pinned bytes.

## Terminal and API

**The UI is a blank page.** The API is serving without built assets. Install the release wheel (which
bundles them) or run `make web-install && make web-build`.

**`421 host_not_allowed`.** The request's `Host` header is not one this instance answers for — usually a
DNS-rebinding attempt, or you reached the server through a hostname it does not know. Add legitimate
names with `ATLAS_TERMINAL_ALLOWED_HOSTS=host1,host2`.

**`403 cross_origin_write_refused`.** A state-changing request came from another origin. Add a
development origin with `ATLAS_TERMINAL_ORIGINS` or use the same origin.

**Serve refuses to bind `0.0.0.0`.** That is the intentional loopback-only policy. If you truly need it,
`--allow-non-loopback` acknowledges the risk; Atlas has no authentication and must sit behind an
authenticating proxy.

## Research workflow

**FOCUS demo exits 2.** The corpus, manifest or snapshots are missing. Run `make focus-corpus` (network)
and `make focus-manifest`; Atlas never manufactures a trust anchor.

**Semantics evaluation refuses to run.** The replay refuses when the live code has drifted from the
frozen commit it is auditing. That is deliberate: results are provenance-bound. Use the archive audit
(`make semantics-holdout-archive`) for historical verification and the post-holdout development runner
for new work.

**A benchmark result differs from the documented number.** Check the corpus version and the commit. Atlas
publishes results with their commit and artifact hashes; a number without those is not comparable.
