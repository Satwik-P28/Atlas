# ADR 0037: backend-enforced data rights

**Status:** accepted (Phase 8)

## Context

A UI warning that a licence may forbid redistribution is not enforcement. A package can be copied
outside the UI, and a derived artifact can reproduce restricted source values.

## Decision

Evaluate rights for every source before packaging, installation, export, sharing and hosting.
Only `public_domain` and `permitted` allow those actions. `restricted`, `user_responsibility` and
unknown statuses fail closed. Installation re-evaluates source declarations and every data-bearing
file, so a forged manifest cannot bypass the policy. Transformations do not erase obligations.
Rights decisions and basis travel in the manifest.

## Consequences

Some research cannot be packaged even locally until the user obtains a separate grant. Package
creation may fail late if a source declaration is incomplete. The enforcement is only as honest as
the stored source metadata; it is not a legal determination or a cryptographic proof of licence.
