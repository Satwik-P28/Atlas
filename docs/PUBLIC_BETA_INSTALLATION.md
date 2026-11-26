# Installing a release build

This page covers the released artifacts. For a source checkout see [QUICKSTART.md](QUICKSTART.md).

## From the release page

Download the wheel, the source distribution and `SHA256SUMS`, then verify before installing:

```bash
sha256sum -c SHA256SUMS          # macOS: shasum -a 256 -c SHA256SUMS
python -m venv .venv
. .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install "atlas_quant-0.2.0b1-py3-none-any.whl[terminal]"
atlas init --db var/atlas.db
atlas doctor --db var/atlas.db
atlas demo --db-path var/demo.db
atlas serve --db var/atlas.db --port 8000
```

The `terminal` extra installs the local HTTP API and static hosting. The wheel already contains the
built terminal and the demonstration fixtures, so no checkout and no Node.js are needed.

Expected: `doctor` reports schema 15, integrity ok and zero foreign-key violations; `demo` exits 0
offline with an evidenced answer; `http://127.0.0.1:8000` serves the terminal and `/api/health`
returns 200 with `release_version`.

## From source

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,terminal]"
.venv/bin/atlas init --db var/atlas.db
.venv/bin/atlas demo --db-path var/demo.db
.venv/bin/atlas serve --db var/atlas.db --port 8000
```

Frontend development:

```bash
npm --prefix web ci
npm --prefix web run dev          # Vite dev server
npm --prefix web run build        # production bundle served by the API and packaged into the wheel
```

## Verify the installation

```bash
.venv/bin/python -m pytest -o addopts='' -q -p no:warnings   # full offline suite
.venv/bin/python scripts/verify_packaged_install.py          # install the built wheel into a clean venv
```

Release-level verification (hashes, licence metadata, real-filing reproduction, certificate
integrity) is in [RELEASE_VERIFICATION.md](RELEASE_VERIFICATION.md).

## Security boundary

The service is unauthenticated and binds to loopback. It rejects foreign `Host` headers and
cross-origin writes, but it is single-user software: do not expose it to a network. See
[SECURITY.md](../SECURITY.md).

## External beta walkthrough

The eleven-step acceptance path (install → issuer → model → assumptions → provenance → save/reopen →
export → second-install reproduction) and the evaluation protocol are in
[ATLAS_BETA_USER_TEST_PLAN.md](ATLAS_BETA_USER_TEST_PLAN.md). Nothing there has been executed by an
external participant yet; see [the beta program](launch/BETA_PROGRAM.md) for how results are recorded
without editing history.
