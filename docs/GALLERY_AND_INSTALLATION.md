# Local gallery and installation

The gallery at `/applications` lists locally installed applications and declarative packs. It is
not a centralized marketplace and makes no reputation, download-count or publisher-verification
claim.

## User flow

1. Build a package from a saved economic analysis, or choose a `.atlas` file.
2. Installation parses and validates the package before touching the database.
3. The gallery shows application identity, version, runtime, reproducibility level, package
   SHA-256, unsigned status, sources and limitations.
4. **Execute package** runs the installed runtime and compares the packaged analysis fingerprint,
   test RMSE, test R² and scenario cost. The result records whether the packaged scenario matched.
5. **Verify integrity** re-reads the original package bytes from the installation.
6. **Download** returns exactly the installed bytes.
7. **Fork** builds a new local package with a new identity, publisher `local.user`, explicit
   fork provenance and preserved limitations. It does not claim publisher endorsement.
8. **Uninstall** deletes the installation and package bytes; research objects and execution
   history remain.

The HTTP routes are `GET /api/applications`, `POST /api/applications/export`,
`POST /api/applications/install`, `GET /api/applications/{id}/open|verify|download`,
`POST /api/applications/{id}/execute|fork`, `GET .../compare` and `DELETE /api/applications/{id}`.
Package bytes cross the API as strict base64. The server enforces limits and never accepts a
client path.

The CLI equivalents are `atlas app list|open|execute|verify|export|fork|compare|uninstall`.
