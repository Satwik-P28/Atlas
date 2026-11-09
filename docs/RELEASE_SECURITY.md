# Release security

## Trust boundaries

- **Research input:** SEC XBRL facts are untrusted external data. They are parsed into typed
  evidence records with source hashes; they are never executed.
- **Provider transport:** compressed responses are untrusted. Input and expanded output are
  both bounded, and a stream without its end-of-stream marker is refused rather than
  returned as a short document (`src/atlas/ingestion/sec_client.py`).
- **Model runtime:** the DCF is a canonical `atlas.model.v1` graph executed by the
  allowlisted operator registry. There is no `eval`, `exec`, dynamic import or shell call in
  the valuation path.
- **Package boundary:** an `atlas.application_package.v1` archive is declarative. It
  contains no Python, JavaScript, shell or native code; path traversal, NUL bytes,
  symlinks, unsupported compression, encryption, oversized expansion and tampering are
  rejected before install.
- **Browser boundary:** the API is read-mostly, CORS-restricted to loopback development
  origins, refuses request bodies above `ATLAS_MAX_REQUEST_BYTES` (8 MiB default), and
  returns structured errors. No secrets are stored in the frontend.
- **Deployment boundary:** the terminal has **no authentication**. It binds loopback by
  default and prints a warning if asked to bind any other address.

## Package integrity

- Content root and per-file SHA-256 are verified on read, install and execute.
- Packages are **unsigned**. The hash proves integrity, not publisher identity; the UI and
  manifest say so explicitly.
- Execution is refused (`inspect_only`) when the compiler or operator versions do not match.

## Transport integrity (Phase 9.2.5)

- Bounded compressed input (64 MiB) and bounded expanded output (64 MiB).
- End-of-stream required; truncation, corrupt CRC/trailer, invalid headers and unexpected
  trailing bytes are refused.
- Concatenated gzip members are decoded in order (RFC 1952); trailing data after a zlib
  `deflate` stream is refused (RFC 1950).
- Response bodies are read in bounded chunks; a declared `Content-Length` above the limit is
  refused before reading.
- Interrupted reads (`IncompleteRead`) are retried and then reported as unavailable, never
  returned as a partial document.
- Regression coverage: `tests/test_release_security_9_2_5.py`, `tests/test_sec_transport_limits.py`.

## Archive integrity

- ZIP entries: absolute/`..` paths, NUL bytes, symlinks, duplicates, encryption and
  unsupported compression are rejected; declared and actual sizes are checked; total
  expanded size is capped (16 MiB for packages).
- FR Y-9C archives: member expansion is capped (512 MiB quarterly archive, 64 MiB dictionary
  members) and read through a streaming handle.

## Data handling

- No credentials, API keys or personal data are needed or stored by this Phase 9 slice.
- SEC fetches are optional and use a declared user agent; downloaded raw payloads stay in
  ignored `var/` paths.
- Evidence ids, accessions and source hashes are retained for inspection; no licensed data
  is redistributed.
- Restricted vendor series remain reachable in earlier commits; see
  `docs/HISTORICAL_DATA_REMEDIATION.md`. No rewrite has been performed.

## Known gaps

- No signature verification or key management.
- No authentication or per-user authorisation: the terminal is local and single-user.
- No sandbox for a future executable extension model; executable extensions remain out of
  scope.
- Dependency scanning is limited to the recorded SBOM and lockfile; no live vulnerability
  feed is integrated.
- No rate limiting on the local API beyond the request-body ceiling; acceptable only
  because the service is loopback-only.
