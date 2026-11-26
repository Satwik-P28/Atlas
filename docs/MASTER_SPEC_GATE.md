# Master specification gate

Status: **v3.2.0 specification updated and identity-pinned; clause-level conformance not yet verified**. The existing v3.0 code-status judgments were not automatically rerun.

## Canonical source

| Property | Verified value |
| --- | --- |
| File | `ATLAS_MASTER_SPEC.md` (repository root) |
| Version | 3.2.0 |
| Date | 2026-11-16 |
| Size | 357,970 bytes |
| SHA-256 | `6ab1a00569a29830deda050c44eaa93dc0f65081be53966ed2a6d00b164447e2` |
| Origin | User-supplied v3.0 baseline, v3.1 Appendices A-D, and v3.2 Appendix E research amendment |
| Tracking commit | `d2ca1662a40618f62e1c3d13ca6f4fe00121c6f7` (v3.2 document commit) |

The repository's `scripts/verify_master_spec.py` now pins the v3.1 size and checksum. Run:

```bash
python scripts/verify_master_spec.py
```

This check establishes only the file's byte identity. It does **not** verify implementation conformance, benchmark acceptance, or completeness of any phase.

## Historical provenance

Earlier audits expected v1.2.0 (155,419 bytes; SHA-256 `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`) and reported that file missing. That was the prior historical baseline, not the current canonical specification. Do not rewrite historical audits or pretend the old v1.2 checksum matches the new version.

## Remaining acceptance work

1. Independently run the v3.1 verifier in a clean checkout.
2. Regenerate and review the traceability matrix covering all 61 canonical sections, Appendices A-E and ICB-01 through ICB-64; ICB-65..75 remain proposed, including the new Appendix D proposals.
3. Compare implemented contracts to the v3.1 desired state; record `implemented`, `partial`, `absent` and `blocked` with evidence.
4. Independently run and publish the appropriate numerical, temporal, rights, security, reproducibility and user-workflow benchmarks.
5. Do not claim institutional-grade adoption, full Phase 9 spec conformance or Phase 10 readiness from document ingestion alone.

## v3.2 scope note

Appendix E specifies the Price Movement Intelligence interface, factor research, market-data/provider integration and institutional numerical-reference program. No new feature status, benchmark execution or source entitlement is implied. ICB-65..75 remain unregistered proposals until acceptance and registry regeneration. Prior v3.1 historical checksum and audit are preserved in Git history.
