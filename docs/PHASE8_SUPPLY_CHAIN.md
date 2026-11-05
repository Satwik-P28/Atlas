# Phase 8 supply chain

Release artifacts are built from the repository with standard-library tooling:

```bash
python scripts/build_phase8_fixtures.py
python scripts/release_manifest.py
python scripts/benchmark_phase8.py
```

`release_manifest.py` hashes every tracked or non-ignored project file except generated artifacts.
It records the Git revision, dirty-worktree flag, Python/platform, file sizes and SHA-256 values.
It also writes a CycloneDX 1.5-shaped SBOM enumerating installed Python distributions.

The fixture package is pinned twice: by its own manifest content root and by the SHA-256 in
`fixtures/phase8/energy_research_pack.json`. Installation verifies both the ZIP entry hashes and
the content root. The pack refuses a mismatched application hash before writing.

This is integrity, not provenance. There is no signing key, transparency log, reproducible-build
attestation, SLSA claim, publisher certificate or trusted gallery. The package manifest says
`signature: null`, `signature_status: "unsigned"` and `publisher_verified: false`. A future signing
contract must define canonical bytes, key distribution, revocation and verifier behavior.

No secret is written by these scripts. `.env`, `.dev.vars`, databases, virtual environments,
downloaded browser libraries and caches are excluded by `.gitignore` and the manifest walker.
