# Engineering Defense

Questions a reviewer will ask about this codebase, with the answers the code actually supports.

## "Isn't a hash-based certificate just a checksum? What does verification add?"

A fingerprint only proves the body has not changed since it was signed. It says nothing about whether the
body was ever true. That is why verification has two passes: arithmetic recomputation from the
certificate's own raw strings, and comparison of every binding against a pinned manifest plus archived
document bytes supplied from outside the certificate. A forger who re-signs a forged body passes the
fingerprint check and fails the second pass.

## "Your adversarial test re-signs the tamper. Doesn't that just prove your own signature code works?"

It proves the opposite of what a naive test would. Because the tamper is re-signed, the fingerprint check
succeeds and the arithmetic plausibly succeeds too for the headline case (change input and result
together). The test therefore isolates the source pass: it is the only thing that catches the forgery. A
test that left the fingerprint stale would pass for the wrong reason.

## "Why four levels instead of valid/invalid?"

Because "the arithmetic works" and "the inputs are real" are different claims with different failure
modes, and collapsing them lets a caller claim more than it checked. `ARITHMETIC_VERIFIED` is a genuinely
useful result — it is what you get from a certificate alone — but it must never be presented as proof the
source existed.

## "Why not just fetch the filing again during verification?"

Live refetching makes verification non-reproducible and couples it to network state and to whatever the
issuer has since filed. Verification runs against archived bytes; live fetch is an explicit opt-in flag
(`--live-sec`), restricted to the approved SEC archive prefix, and its absence is reported as missing
evidence.

## "Why is the manifest keyed by table digest and coordinates instead of document id?"

Document and table ids are regenerated on each ingestion, so a manifest keyed by them would invalidate on
every rebuild. `(table_sha256, row, column)` is stable for identical bytes and changes the moment the table
content changes, which is exactly the property an anchor needs.

## "An attacker who rewrites both the manifest and the snapshots defeats this."

Yes. The manifest is unsigned. Source verification proves consistency with a snapshot; it does not
establish that the snapshot is authentic or that it was served at a given time. Authenticity is a
provenance problem — signed manifests, vendor attestations, or institutional custody — and this project
documents the gap rather than papering over it with a self-signed anchor.

## "Isn't regenerating a missing manifest on demand more user-friendly?"

It is, and it destroys the guarantee: verification would then manufacture its own trust anchor from
whatever is on disk. Strict verification reports the missing anchor and exits `2`. Creating one is a
separate, explicit command (`make focus-manifest`).

## "You have three implementations of the same arithmetic. Isn't that duplication?"

It is deliberate: the point is independent agreement. The FEC computes, `financial_verification`
recomputes with `Fraction`, and the verifier re-parses the printed strings a third time. Shared reference
vectors pin all three, and disagreement is a hard error rather than a tie-break.

## "Why is unknown scale `None` and not `0`?"

Because `0` is a valid scale — it means the printed number is the amount. Returning `0` for an unreadable
unit banner converts "I don't know" into a confident answer that can be off by orders of magnitude. This
was a real defect: a 3M figure was reported as `34,229` instead of `34,229,000,000`.

## "Ten of thirteen. Isn't that a weak result?"

It is an honest one. Three refusals are reported separately because they mean different things: one is
correct policy (the statement has no such line), one is correct temporal behaviour (the evidence was not
public yet), and one is a defect (the FY2018 figure exists and the resolver misses it). Collapsing them
into "three abstentions" would hide the only real failure.

## "What would you do with more time?"

Add XBRL fact corroboration for scale and period, extend the manifest to a signed anchor with recorded
provenance, fix the FY2018 resolver gap, and widen the corpus beyond three issuers. Those are named
limitations, not roadmap promises.

## "How do you know the demo is actually checking anything?"

Three negative controls, all reproducible: a missing manifest exits `2`, a manifest with a perturbed cell
exits `1`, and a tampered certificate exits `1` while the unmodified one exits `0` and reports
`SOURCE_VERIFIED`. A demo that only ever returns success would not distinguish those cases.
