# Phase 8 release procedure

1. Confirm the working tree and schema: `atlas doctor`.
2. Run the focused suite: `.venv/bin/python -m pytest -o addopts='' -q -p no:warnings tests/test_phase8_applications.py`.
3. Run the full backend suite and the frontend build/typecheck.
4. Rebuild the pinned artifact with `python scripts/build_phase8_fixtures.py` only when source
   content intentionally changes; commit the package and pack together.
5. Regenerate `artifacts/phase8_benchmark.json` and `artifacts/release_manifest.json`.
6. Start the local server, run `web/e2e/phase8.mjs`, and inspect the gallery screenshots.
7. Commit locally. Do not push or deploy without explicit authorization.

## Compatibility

Schema 10 is required. Existing schema 9 databases upgrade through `atlas migrate`, which creates
and verifies a backup first. Applications targeting a different compiler/operator version install
as `inspect_only`; execution refuses to fabricate a result.

## Known release blockers

The genuine `ATLAS_MASTER_SPEC.md` v1.2.0 is absent from the repository. Phase 8 therefore cannot
claim master-spec conformance or satisfy the import/checksum gate. This release is internally
tested against the in-repo Phase 8 contract and the existing Phase 7 interfaces, but that is not a
substitute for the missing authority.

There is no signed-package verification, no trusted remote gallery, no executable extension
sandbox, no real-estate pack, no collaboration/multiplayer layer and no durable scheduler. These
are documented non-capabilities, not hidden implementations.
