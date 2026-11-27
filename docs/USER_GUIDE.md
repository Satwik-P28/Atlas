# User guide

A working guide to the Atlas v0.2.0-beta.2 command line and terminal. It documents what exists; for
what does not, see [known limitations](KNOWN_LIMITATIONS.md).

## Mental model

Three layers, in this order:

1. **Evidence.** Facts are immutable observations with provenance, availability semantics and revision
   lineage. Nothing is overwritten; a correction is a new record with a supersession link.
2. **Computation.** A computation names its inputs (bound evidence identities), its units and its
   formula. It is compiled through the Financial-Economic Compiler and recomputed by an independent
   exact-arithmetic verifier.
3. **Claim.** A claim (an answer, a memo clause, a model output) carries the evidence and the
   computation, or it carries a refusal with a reason.

If you read a number in Atlas, you can always ask it for layer 1 and layer 2.

## Database lifecycle

```bash
atlas --db var/atlas.db init        # create or migrate
atlas --db var/atlas.db doctor      # status, schema, integrity, foreign keys, counts
atlas --db var/atlas.db migrate     # backup + migrate + verify
atlas --db var/atlas.db stats       # row counts per area
```

`--db` is a global option and must be given before the subcommand. There is no `--version` flag:
`atlas doctor --json` reports the release version (`release_version`), and
`python -c "import atlas; print(atlas.__release_label__)"` prints the release label. Commands that
manage their own database file (`demo`, `serve`, `mcp`) accept `--db-path` as well.

`doctor` writes a JSON document (`atlas.doctor.v1`) with `--json`. It is the first thing to run when
something looks wrong; it exits non-zero when the database needs attention.

## Ingesting filings

```bash
export ATLAS_SEC_USER_AGENT='YourApp/1.0 you@example.com'
atlas sec sync --cik 0000320193 --db var/atlas.db
atlas sec history --cik 0000320193 --db var/atlas.db
atlas sec filings --cik 0000320193 --db var/atlas.db
```

Ingestion stores submissions metadata, company facts and (optionally) primary documents. Availability
is recorded explicitly: an observed instant where one exists, a date where only a date exists, and a
modelled bound where only EDGAR acceptance plus a publication lag is available.

## Retrieving facts point-in-time

```bash
atlas facts --cik 0000320193 --concept revenue --as-of 2026-11-01 --db var/atlas.db --json
atlas asof --cik 0000320193 --concept revenue --as-of 2026-11-01 --db var/atlas.db
atlas entity show --cik 0000320193 --db var/atlas.db
```

`--as-of` filters by availability, not by fiscal period. A fact restated later resolves to the value
that was available at the instant you ask about; the revision lineage stays inspectable.

## Certificates

An accepted computation can be issued as `atlas.research_certificate.v1`. Verification is a separate
command:

```bash
atlas verify-certificate --manifest artifacts/focus_source_manifest.json \
  --snapshots var/focus/snapshots --strict certificate.json
```

| Level | Meaning |
|---|---|
| `SOURCE_VERIFIED` | Arithmetic agrees, and the certificate's digests, coordinates, label, raw text, period, scale and currency match the pinned manifest and archived bytes |
| `ARITHMETIC_VERIFIED` | Arithmetic agrees but no trusted evidence was supplied; the inputs are unproven |
| `SOURCE_UNVERIFIED` | Evidence was offered but is unusable |
| `INVALID` | Fingerprint, structure, arithmetic or source comparison failed |

Verification of internal consistency is not proof of economic interpretation. Atlas keeps that
distinction in the result (`verified_but_not_proven_correct`).

## Application packages

```bash
atlas app init my-study                      # scaffold a declarative project
atlas app build my-study --out my-study.atlas
atlas app inspect my-study.atlas
atlas app verify my-study.atlas
atlas --db var/atlas.db app install my-study.atlas
atlas app execute <install_id> --db var/atlas.db
atlas app export <install_id> --db var/atlas.db --out replay.atlas
atlas app compare <left> <right> --db var/atlas.db
atlas app uninstall <install_id> --db var/atlas.db
```

Packages are declarative: data snapshots, a model specification and expected outputs. No Python,
JavaScript, shell or native code inside a package is ever executed. Rights are checked before install,
and a package whose source does not permit packaging is refused rather than silently included.

## Research memos

Memoranda are research objects with clauses bound to evidence. They export as Markdown, HTML or JSON;
revision history is append-only. `atlas app export` produces a replayable package with a verification
manifest.

## The terminal

```bash
atlas serve --db-path var/atlas.db --port 8000
```

Pages: Companies, Company, Filings, Research, Workstation, Markets, Screener, Watchlists, Workspaces,
Applications, Equity Research, Institutional, Economic, Lab, Learning.

The API is documented at `/api/docs` and `/api/openapi.json`. All endpoints are unauthenticated and
local; the service rejects foreign `Host` headers and cross-origin writes. Do not expose it.

## Choosing a workflow

| Goal | Path |
|---|---|
| Learn what Atlas does | `atlas demo`, then the terminal on the demo database |
| Check a real filing's figure | `atlas sec sync` → `atlas facts --as-of` → issue/verify a certificate |
| Reproduce a published result | `atlas app install <package>` → `atlas app execute` → compare expected outputs |
| Investigate a price move | terminal → Company → price explanation (needs a price series you may store) |
| Build your own study | `atlas app init` and the package specification in `docs/APPLICATION_PACKAGE_SPEC.md` |

## Practical notes

- Databases are SQLite files. Back them up with `atlas migrate` (which snapshots first) or by copying
  the file plus `-wal`/`-shm` while Atlas is stopped.
- `var/` is untracked scratch space. Nothing under it belongs in a commit.
- Everything numeric is reported with its unit and scale. If a value looks off by a factor of a
  thousand, check the scale field before doubting the number.
- When Atlas refuses, read the reason code: `definitional_ambiguity`, `scope_mismatch`,
  `mixed_reporting_scope`, `availability_unknown` and the rest are designed to tell you what would
  have to be true for the question to be answerable.
