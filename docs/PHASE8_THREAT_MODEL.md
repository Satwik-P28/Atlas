# Phase 8 threat model

## Assets

Evidence and research integrity; source rights; user research objects; the local database; package
and execution history; provider credentials and secrets (not stored in packages).

## Adversaries

A malicious package author; a user who imports an untrusted file; a compromised source archive; a
package that lies about rights or dependencies; accidental path traversal; a future remote gallery
operator. Atlas itself and the local OS user are trusted in this phase.

## Mitigations

The package reader rejects traversal, symlinks, directories, duplicate/encrypted entries, unsafe
suffixes and size abuse. The manifest binds every file to SHA-256 and the application to a content
root. Installation revalidates source rights and data-bearing files. Runtime dispatch is an
allow-list. SQL uses bound parameters; package data never becomes SQL or a filesystem path.
Execution writes only application/execution rows and existing research objects. Uninstall retains
research objects.

## Residual risks

A valid but computationally expensive declarative model can consume CPU or memory within the
documented local limits; there is no cgroup or per-package quota. A malicious source declaration
can lie at ingestion time; rights are enforced from the stored metadata, not from cryptography.
Unsigned packages are not attributable. An attacker with local database write access can alter
state; Atlas is not a remote multi-tenant service. SHA-256 collisions are treated as infeasible,
but a correct hash is not a trust decision.

## Out of scope

Third-party executable plugins, Python subprocess “sandboxes”, network fetching from package
content, live trading, credential access, private-location data, collaboration and a public
marketplace.
