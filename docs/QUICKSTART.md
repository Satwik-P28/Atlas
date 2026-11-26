# Quickstart

Atlas installs from a wheel and runs on your machine. You do not need Node.js, a database server,
a paid data feed, an LLM subscription, or a development checkout.

## 1. Install (Linux, macOS, Windows)

Python 3.11 or 3.12.

```bash
python -m venv .venv
. .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install "atlas_quant-0.2.0b1-py3-none-any.whl[terminal]"
```

Windows notes: use PowerShell, and if activation is blocked run
`Set-ExecutionPolicy -Scope Process Bypass` for that shell only. Paths with spaces work.

## 2. Run the offline demonstration (no network)

```bash
atlas demo
```

This creates `~/.atlas/atlas.db`, ingests a project-authored synthetic 10-K (not a real company),
opens the terminal on loopback, and builds a demonstration answer, certificate and memo. Everything
in it is synthetic and is labelled as such in the interface.

Open the address it prints (usually `http://127.0.0.1:3000`). Try:

- **Answer certificates** — company "Atlas Demonstration Industries", concept "gross profit",
  period `2023`; then *Build certificate* → *Verify independently*.
- **Command palette** — `Ctrl+K` / `Cmd+K`, type a symbol, press Enter.
- **Memos** — the Valuation workspace can build and save an evidence-grounded memo, then export PDF.

## 3. Work with a real company (network)

The SEC requires a descriptive User-Agent with a contact address; Atlas will not invent one.

```bash
export ATLAS_SEC_USER_AGENT="Your Name you@example.org"     # Windows: setx ATLAS_SEC_USER_AGENT "..."
atlas sec sync --cik 320193                                 # Apple Inc.
atlas serve
```

`atlas sec sync` stores derived facts, identifiers and document digests — not the filing text.
To parse a filing's tables and text, ingest it from the UI (Data → ingest) or through the API; the
document is stored locally and classified as your responsibility, so exports that depend on it are
gated.

## 4. MCP clients

```bash
atlas mcp                       # read-only: 14 tools, no mutations
atlas mcp --allow-mutations     # adds save_research_object
```

Example configuration for any MCP host that launches stdio servers:

```json
{
  "mcpServers": {
    "atlas": { "command": "atlas", "args": ["--db", "/home/you/.atlas/atlas.db", "mcp"] }
  }
}
```

Tested with the official `mcp` Python SDK (protocol `2024-11-05`). Other clients are expected to
work because the transport and schema are standard, but they have not been tested here.

## 5. Backup, restore and upgrade

```bash
cp ~/.atlas/atlas.db ~/atlas-backup-$(date +%F).db   # backup: one file
atlas --db ~/atlas-backup-2026-11-24.db verify       # check it opens and verifies
pip install --upgrade "<newer-wheel>.whl[terminal]"   # upgrade: schema migrations run on open
```

Restore is the reverse: stop the server, copy the backup over the database path, start again.
Certificate fingerprints bind the data and cutoff, so a restored database reproduces the same
values.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `atlas: command not found` | virtual environment not active | activate `.venv`, or use `python -m atlas` |
| `ValueError: SEC requires a User-Agent with contact details` | no contact identity | set `ATLAS_SEC_USER_AGENT` |
| The browser shows an empty page after `atlas demo` | the bundled frontend was not found | reinstall the wheel; the frontend ships inside it |
| `atlas serve` starts but pages do not load | a proxy is rewriting Host headers | open `http://127.0.0.1:<port>` directly |
| Refused answers on a real company | the concept is not in a parsed filing for that period | ingest the filing first, then retry |

Known limitations: [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md). Nothing here is investment advice.
