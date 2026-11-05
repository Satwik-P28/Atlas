# Release security — Phase 9

## Trust boundaries

- **Research input:** SEC XBRL facts are untrusted external data. They are parsed into typed
  evidence records with source hashes; they are never executed.
- **Model runtime:** the DCF is a canonical `atlas.model.v1` graph executed by the
  allowlisted operator registry. There is no `eval`, `exec`, dynamic import or shell call in
  the valuation path.
- **Package boundary:** an `atlas.application_package.v1` archive is declarative. It
  contains no Python, JavaScript, shell or native code; path traversal, unexpected suffixes
  and tampering are rejected before install.
- **Browser boundary:** the API is read-mostly, CORS-restricted to loopback development
  origins, and returns structured errors. No secrets are stored in the frontend.

## Package integrity

- Content root and per-file SHA-256 are verified on read, install and execute.
- Packages are **unsigned**. The hash proves integrity, not publisher identity; the UI and
  manifest say so explicitly.
- Execution is refused (`inspect_only`) when the compiler or operator versions do not match.

## Data handling

- No credentials, API keys or personal data are needed or stored by this Phase 9 slice.
- SEC fetches are optional and use a declared user agent; downloaded raw payloads stay in
  ignored `var/` paths.
- Evidence ids, accessions and source hashes are retained for inspection; no licensed data
  is redistributed.

## Known gaps

- No signature verification or key management.
- No authentication or per-user authorisation: the terminal is local.
- No sandbox for a future executable extension model; executable extensions remain out of
  scope.
- Dependency scanning is limited to the recorded SBOM and lockfile; no live vulnerability
  feed is integrated.
