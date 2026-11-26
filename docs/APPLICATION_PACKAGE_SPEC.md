# Application package specification

Schema: `atlas.application_package.v1`. A package is a ZIP containing `manifest.json`, an
`application.json`, and approved declarative artifacts. It is not a Python wheel, a plugin
bundle, or a container image.

## Determinism

Entries are sorted and written with fixed 1980-01-01 timestamps, fixed Unix mode `100644`,
deflate level 9 and no directory or symlink entries. Canonical JSON sorts keys and uses compact
separators. The content root hashes the application document, every file record, source metadata,
rights decisions, dependencies, capabilities and reproducibility declaration. Building the same
application, files and metadata twice produces identical bytes; this is tested.

## Manifest

Required fields are `schema`, `format_version`, `package_id`, `content_root`, `created_at`,
`application`, `application_sha256`, `sources`, `rights`, `dependencies`, `capabilities`,
`reproducibility`, `files`, `signature`, `signature_status`, `trust` and `build`.
`package_id` is `APKG-` plus the first 20 hex characters of the content root. Each file record
contains path, SHA-256, byte size, media type, role, rights and source IDs.

## Accepted content

Only `.json`, `.csv`, `.md` and `.txt` payloads are accepted. Paths must be relative, contain no
`.` or `..` component, no backslash, no colon and no absolute prefix. `manifest.json` is reserved.
ZIP directories, symlinks, duplicate entries and encrypted entries are rejected. Limits are
64 files, 16 MiB uncompressed, 8 MiB compressed, 8 MiB per file and 512 KiB manifest. Nested
objects whose keys look executable (`code`, `python`, `script`, `command`, `entrypoint`, etc.)
are rejected.

## Trust

SHA-256 and the content root prove byte integrity. They do not prove who created the package.
Signature verification is not implemented, so signed packages are rejected and `signature` must
be `null`. Installation labels every package `unsigned` and `publisher_verified: false`.
The pinned first-party fixture has SHA-256
`92ab1bf753438a0f534a080697abca9c638da11521e13c1dc43700883c82227b`; that number is not an identity
certificate.
