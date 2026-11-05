# Phase 8 limitations

- **Missing authority.** The genuine `ATLAS_MASTER_SPEC.md` v1.2.0 was not supplied. No
  master-spec conformance, checksum import or completion-gate 2 claim is made.
- **Unsigned packages.** No signature algorithm, key management, revocation or publisher
  verification is implemented. Integrity is SHA-256 only.
- **No executable extensions.** There is no third-party code sandbox, interpreter isolation,
  capability broker or cgroup. “No untrusted code executes” is the design, not a claim that all
  untrusted data is harmless.
- **No remote marketplace.** The gallery is local. There is no upload service, reputation,
  moderation, tenant isolation or public hosting.
- **Computational, not raw, reproducibility.** The flagship package carries a canonical daily
  panel, not the raw EIA/NOAA bytes. Rebuilding the upstream archive is not guaranteed.
- **Econometric limits.** One region, one year, one primary station; test RMSE 2,956.58 MW,
  test R² −0.8935, positive bias; association only; no identification. The company, load,
  contract, price and revenue are hypothetical.
- **Spatial semantics.** Station differences are spatial representativeness, not logical
  contradictions. Genuine same-location value conflicts would remain unresolved.
- **Migration.** Only SQLite schema 9→10 is verified on Linux. Cross-platform backup/restore and
  downgrades are not tested. Older binaries refuse schema 10.
- **No real-estate or collaboration phase.** Those are intentionally absent because the core gates
  were the priority and the master spec is missing.
