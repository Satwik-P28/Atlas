# Master specification gate

Status: **v3.0.0 received and integrity-pinned; clause-level conformance not yet verified**.

## Canonical source

| Property | Verified value |
| --- | --- |
| File | `ATLAS_MASTER_SPEC.md` (repository root) |
| Version | 3.0.0 |
| Date | 2026-11-09 |
| Size | 289,963 bytes |
| SHA-256 | `c1228db93e66a04fb211bea85f6c978289a6040b1f655f934da76498c8c4752d` |
| Origin | User-supplied `ATLAS_MASTER_SPEC_V3_FINAL.md`, copied without edits |
| Tracking commit | `9e436b7629a1c19cd705021b96a7a9bded507527` |

The repository's `scripts/verify_master_spec.py` now pins the v3.0 size and checksum. Run:

```bash
python scripts/verify_master_spec.py
```

This check establishes only the file's byte identity. It does **not** verify implementation conformance, benchmark acceptance, or completeness of any phase.

## Historical provenance

Earlier audits expected v1.2.0 (155,419 bytes; SHA-256 `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`) and reported that file missing. That was the prior historical baseline, not the current canonical specification. Do not rewrite historical audits or pretend the old v1.2 checksum matches the new version.

## Remaining acceptance work

1. Independently run the v3.0 verifier in a clean checkout.
2. Build a traceability matrix covering all v3.0 sections and ICB-01 through ICB-48.
3. Compare implemented contracts to the v3.0 desired state; record `implemented`, `partial`, `absent` and `blocked` with evidence.
4. Independently run and publish the appropriate numerical, temporal, rights, security, reproducibility and user-workflow benchmarks.
5. Do not claim institutional-grade adoption, full Phase 9 spec conformance or Phase 10 readiness from document ingestion alone.
