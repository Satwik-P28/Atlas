# ADR 0039: integrity without signatures

**Status:** accepted (Phase 8)

## Context

The implementation needs tamper detection now, but inventing a signing scheme or treating a hash as
publisher identity would create a false security claim. Key distribution, revocation and canonical
signing bytes are not specified.

## Decision

Ship SHA-256 and content-root verification only. The manifest requires `signature: null` and
`signature_status: "unsigned"`. Installation and the gallery show `publisher_verified: false`.
Signed packages are rejected until a reviewed verifier exists. No custom cryptography is used.

## Consequences

Users can detect corruption and accidental modification but cannot authenticate a publisher.
Packages from strangers should be treated as untrusted declarations. A future signature contract
must define canonical bytes, trust roots, expiration, revocation, transparency and failure
semantics; adding a base64 blob to the manifest is not enough.
