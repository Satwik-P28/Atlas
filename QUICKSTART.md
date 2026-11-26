# Quickstart

Atlas v0.2.0-beta.1 (`0.2.0b1`). Python 3.11+ on Linux, macOS or Windows. No Node, no database
server, no paid data provider and no API key are required for the local workflows.

## 1. Install

From a release artifact (recommended):

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install "atlas_quant-0.2.0b1-py3-none-any.whl[terminal]"
```

From a source checkout:

```bash
make install            # creates .venv and installs .[dev]
# optional: the terminal extra, the numerical stack, columnar import
.venv/bin/python -m pip install -e ".[dev,terminal,learning,columnar,optimization]"
```

The wheel bundles the built terminal and the demonstration fixture subset, so `atlas serve` and
`atlas demo` work without a source tree or a Node toolchain. `atlas doctor` prints what is missing if
something is absent.

## 2. Create a database

```bash
atlas init --db var/atlas.db        # create and migrate
atlas doctor --db var/atlas.db      # schema, integrity, foreign keys, release version
atlas migrate --db var/atlas.db     # backup, migrate and verify (use after an upgrade)
```

`atlas doctor` exits `0` only when the schema is current, SQLite integrity is `ok` and there are no
foreign-key violations. It reports the installed release version separately from the HTTP API
contract version.

## 3. Run the offline demonstration

```bash
atlas demo --db-path var/demo.db
```

Everything in the demonstration runs offline against archived SEC payloads and clearly labelled
synthetic market series. It prints the evidence each section relied on; `--keep` reuses the database
instead of rebuilding it.

## 4. Start the terminal

```bash
atlas serve --db var/atlas.db --port 8000
```

Open <http://127.0.0.1:8000>. The service is unauthenticated and loopback-only. A non-loopback bind
requires the explicit `--allow-non-loopback` acknowledgement and must sit behind an authenticating
proxy; Atlas provides no authentication.

## 5. Ingest real filings (network, optional)

```bash
export ATLAS_SEC_USER_AGENT='YourApp/1.0 you@example.com'
atlas sec sync --cik 0000320193 --db var/atlas.db
atlas sec filings --cik 0000320193 --db var/atlas.db
atlas facts --cik 0000320193 --concept revenue --as-of 2026-11-01 --db var/atlas.db --json
```

SEC access requires an identifying user agent and stays within SEC fair-access limits. Point-in-time
retrieval is explicit: pass `--as-of` and, for historical claims, the historical mode, so Atlas
filters by what was available at that instant rather than by what exists today.

## 6. Verify an answer instead of trusting it

Accepted answers carry an evidence certificate. Verification is a separate command that re-checks the
arithmetic and compares bound evidence against pinned bytes:

```bash
atlas verify-certificate --manifest artifacts/focus_source_manifest.json \
  --snapshots var/focus/snapshots --strict certificate.json
```

The result is one of `SOURCE_VERIFIED`, `ARITHMETIC_VERIFIED`, `SOURCE_UNVERIFIED` or `INVALID`.
`ARITHMETIC_VERIFIED` means the arithmetic is consistent but the inputs themselves are unproven — a
distinction Atlas keeps visible everywhere.

## 7. Reproduce the offline filing demonstration

```bash
export ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com'
make focus-corpus       # network: fetch and archive exact SEC bytes
make focus-manifest     # explicit trust anchor over those bytes
make focus-demo         # offline: 13 cases, certificates, 29 tamper attempts, refusals
```

`make focus-demo` exits `0` only when every required check passes, `1` when a check fails or a tamper
is accepted, and `2` when the corpus, manifest or snapshots are missing (it never manufactures a trust
anchor).

## Common problems

| Symptom | Cause and fix |
|---|---|
| `no built frontend found` on `atlas serve` | A source install without `web/dist`. Install the release wheel, or run `make web-install && make web-build`. |
| `atlas doctor` exits 1 with `attention_required` | Schema behind the release, integrity failure or foreign-key violation. Run `atlas migrate --db <path>`. |
| `atlas demo` reports missing fixtures | A source install with a deleted `fixtures/` tree, or a wheel built without staged fixtures. Reinstall the release artifact. |
| SEC ingestion refuses or returns 403 | Missing or unhelpful `ATLAS_SEC_USER_AGENT`, or rate limiting. Set an identifying agent and retry later. |
| Serve refuses to bind an address | Loopback-only policy. Use `--allow-non-loopback` only behind an authenticating proxy. |

More in [troubleshooting](docs/TROUBLESHOOTING.md) and [known limitations](docs/KNOWN_LIMITATIONS.md).
