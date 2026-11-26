# Security policy

## Scope and threat model

Atlas v0.2.0-beta.1 is a **local-first, single-user** research system. It has no accounts, no
multi-tenancy and no authentication. The security boundary is the local machine and the user's own
data, not a network perimeter.

What Atlas is designed to resist:

| Threat | Control |
|---|---|
| Network exposure of an unauthenticated API | Loopback-only default bind; a non-loopback bind requires an explicit acknowledgement and is reported as unsafe, not authenticated (`atlas.terminal.exposure`) |
| DNS rebinding of the local API | `Host` header allowlist (`127.0.0.1`, `localhost`, `::1`, configured hosts); foreign hosts get `421 host_not_allowed` before any handler runs |
| Cross-origin writes from a hostile page | State-changing requests from a foreign `Origin` get `403 cross_origin_write_refused`; CORS is restricted to configured origins |
| Oversized or compressed request bombs | Request body ceiling, bounded reads, gzip/deflate/zip bomb refusal with integrity checks |
| Malicious uploaded packages | Declarative packages only: no Python, JavaScript, shell or native code is ever executed from a package; rights and integrity are checked before install |
| Unbounded archive extraction | Path traversal, NUL-byte names, unsupported compression and truncated members are refused |
| Credential leakage in the repository | No `.env` or credential files are tracked; `scripts/audit_distribution.py` scans the tree and history for secret shapes; CI fails if restricted data appears under `fixtures/` |
| Prompt injection through retrieved documents | Retrieved filings are data. Atlas has no LLM in its answer path, so retrieved text cannot direct execution, and no tool call is derived from document content |
| Path traversal in database or export paths | Explicit path handling with containment checks in storage and export paths |

What is explicitly **not** provided: authentication, authorisation, encryption at rest, TLS,
multi-user isolation, sandboxing of the local process, or protection against a local attacker who can
already read your files. Do not deploy an Atlas API on a public network.

## Secrets and data

- No API keys are required for the local workflows. Optional providers read credentials from the
  environment only; nothing is written into the repository or the database.
- Retrieved documents and databases stay local under `var/`, which is not tracked.
- Market data you import is your responsibility: check the provider's terms before storing or
  redistributing it. Atlas records provenance and redistribution class per source and refuses to
  package sources whose redistribution class does not allow it.

## Supported versions

Only the current release candidate line (`0.2.0b1`) is supported. Earlier trees are research
snapshots without security maintenance.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Report it privately to the repository
maintainer through the GitHub "Report a vulnerability" advisory flow on
<https://github.com/Satwik-P28/Atlas>, or by direct message if advisories are unavailable.

Please include: affected version or commit, the component (API, ingestion, package runtime, storage),
a minimal reproduction, the impact you believe it has, and whether the issue requires local access.
Do not include real credentials or third-party licensed data in a report.

Expected handling: acknowledgement within 7 days, an initial assessment within 14 days, and a fix or
a documented decision in the next release. Atlas is a research project maintained without a security
team; these are targets, not a contractual SLA.

## Verifying your own copy

```bash
python scripts/audit_distribution.py      # tracked tree and history: restricted data, secret shapes
python scripts/verify_distributable_fixtures.py
atlas doctor --db var/atlas.db
python -m pytest -q tests/test_local_guard.py
```

Security-relevant behaviour is covered by `tests/test_release_security_9_2_5.py`,
`tests/test_local_guard.py`, `tests/test_sec_transport_limits.py` and the application package tests.
