# Application security model

Phase 8 deliberately implements a data-only extension surface.

## Enforced boundary

- Package parsers accept only ZIP entries with approved declarative suffixes and safe relative
  paths. Traversal, symlinks, duplicate entries, encryption and oversized content are rejected.
- Application documents and manifests are recursively scanned for executable keys.
- Installation validates the manifest, application, every file hash, the content root, source
  rights and runtime/compiler/operator dependencies before writing.
- Installation writes the research object and installation row in one transaction. A failure
  rolls back both.
- Execution dispatches only to `atlas.fec.model.v1` and
  `atlas.economic.weather_demand.v1`. It never imports package code.
- A package cannot request filesystem, network, credentials, process, all-dataset or
  cross-user capabilities; those requests fail validation.
- Uninstall preserves research objects and execution history, preventing a destructive silent
  rewrite of cited research.

## Explicit non-guarantees

There is no signature verifier, publisher identity proof, remote gallery trust, capability
broker, OS sandbox, resource cgroup or denial-of-service isolation for a maliciously expensive but
valid declarative model. The local user is trusted to install packages they choose. Networked
multi-tenant hosting and third-party executable extensions are outside this phase.

The consistent summary is: **no untrusted executable code executes**, not "all untrusted input is
safe". Parser and resource-limit tests cover malformed inputs; they do not turn SHA-256 into a
publisher signature.
