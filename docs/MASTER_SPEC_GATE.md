# Master specification gate

Status: **blocked**. The genuine `ATLAS_MASTER_SPEC.md` version 1.2.0 has not been
imported.

## Required artefact

| Property | Expected |
| --- | --- |
| File | `ATLAS_MASTER_SPEC.md` |
| Version | 1.2.0 |
| Size | 155,419 bytes |
| SHA-256 | `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9` |

## What was checked

The repository root, `docs/`, and the workspace/home search paths were searched again on
2026-11-06 during the final Phase 9.2 correction. No candidate or attachment path was
available. No size or hash could be verified, and no file was committed. No replacement
document was generated.

The common-equity valuation gate is now closed independently of this blocked transfer.
Master-spec conformance and Phase 9 completion still must not be claimed.

## How to close the gate

1. Place the supplied file at the repository root as `ATLAS_MASTER_SPEC.md`.
2. Run `python scripts/verify_master_spec.py`.
3. The script exits 0 only when both the byte length and SHA-256 match; then commit the
   file unchanged.

Until step 3 succeeds, Phase 9 completion must not be reported, and this gate remains the
first open item in the project.
