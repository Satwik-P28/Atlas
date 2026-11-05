# Domain pack specification

Schema: `atlas.domain_pack.v1`. A domain pack contributes metadata, model templates, source and
rights declarations, resource limits, test vectors and packaged applications. It cannot register
code, add operators, change the FEC, execute a subprocess or edit canonical evidence.

## Required contract

A pack declares `pack_id`, `name`, semantic `version`, `publisher`, `license`,
`compatibility`, `kind`, `dependencies`, supported `capabilities`, `sources`, `resources`,
`object_types`, `validation`, at least one `test_vector`, non-empty `limitations`, an
`applications` list and `created_at`.

`kind` must be `declarative`. Unknown capabilities, executable-looking keys, path traversal and
non-`.atlas` application references are rejected. Each referenced package is validated before any
database write. If a declared SHA-256 is present it must match the package bytes.

## Installation semantics

Installation is one SQLite transaction. Embedded applications are installed through the ordinary
application lifecycle; then the pack record is written. A failure rolls everything back. A
repeated install of the same digest is idempotent; the same pack id/version/publisher with
different content is refused.

Uninstall removes only pack metadata. Installed applications and research objects remain, because
removing a pack is not consent to destroy research that may now be cited elsewhere. Applications
must be removed explicitly. The first-party pack is
`fixtures/phase8/energy_research_pack.json`, which pins the real weather-demand package.

No executable extension contract exists in Phase 8. A future extension proposal needs an isolate,
resource limits, capability mediation, audit, revocation and a supply-chain design; a Python
subprocess or virtual environment is not a sandbox.
