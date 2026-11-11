# Master specification gate

Status: **v3.1.0 specification updated and identity-pinned; clause-level conformance not yet verified**. The existing v3.0 code-status judgments were not automatically rerun.

## Canonical source

| Property | Verified value |
| --- | --- |
| File | `ATLAS_MASTER_SPEC.md` (repository root) |
| Version | 3.1.0 |
| Date | 2026-11-11 |
| Size | 333,547 bytes |
| SHA-256 | `d1800cfea35d973e2ff2b3570f8bf564fd3a7aceabca2f623ec5de17931a1111` |
| Origin | User-supplied v3.0 baseline plus reviewed v3.1 Appendix A-D amendment |
| Tracking commit | `8b094eb7434b75d461bf32543290fdfb47c21639` |

The repository's `scripts/verify_master_spec.py` now pins the v3.1 size and checksum. Run:

```bash
python scripts/verify_master_spec.py
```

This check establishes only the file's byte identity. It does **not** verify implementation conformance, benchmark acceptance, or completeness of any phase.

## Historical provenance

Earlier audits expected v1.2.0 (155,419 bytes; SHA-256 `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`) and reported that file missing. That was the prior historical baseline, not the current canonical specification. Do not rewrite historical audits or pretend the old v1.2 checksum matches the new version.

## Remaining acceptance work

1. Independently run the v3.1 verifier in a clean checkout.
2. Regenerate and review the traceability matrix covering all 61 canonical sections and ICB-01 through ICB-64, including the new Appendix D proposals.
3. Compare implemented contracts to the v3.1 desired state; record `implemented`, `partial`, `absent` and `blocked` with evidence.
4. Independently run and publish the appropriate numerical, temporal, rights, security, reproducibility and user-workflow benchmarks.
5. Do not claim institutional-grade adoption, full Phase 9 spec conformance or Phase 10 readiness from document ingestion alone.
