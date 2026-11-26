# ADR 0035: deterministic declarative application packages

**Status:** accepted (Phase 8)

## Context

Portable research needs an inspectable artifact that can be copied without a server. ZIP is
ubiquitous but its default timestamps, ordering and metadata are nondeterministic. A tar archive or
a directory tree would make accidental differences harder to detect.

## Decision

Use a ZIP with sorted entries, fixed 1980 timestamps, fixed modes, no directories or symlinks, and
a canonical JSON manifest. Bind every file to SHA-256 and the whole application to a content root.
Restrict payloads to JSON, CSV, Markdown and text. Reject undeclared files, executable suffixes and
unsafe paths. Signatures remain `null`.

## Consequences

Identical application content produces identical bytes, and tampering is detectable. The format is
easy to inspect with standard tools and does not execute code. It is not a signature, cannot carry
binary model weights, and requires re-export when provenance fields such as a generation timestamp
change. A future binary artifact type needs a separate contract, not a suffix exception.
