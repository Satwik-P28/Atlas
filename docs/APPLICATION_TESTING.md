# Application testing

`tests/test_phase8_applications.py` contains 15 independent acceptance tests. The suite builds
the package from the real 2023 panel; it does not use a mocked application result.

## Coverage

- Schema 10 and the three new tables.
- Byte determinism for repeated builds with the same application, files and metadata.
- Manifest identity, content root, file hashes, source rights and unsigned status.
- Rejection of traversal paths, executable file types, undeclared files, malformed archives and
  tampered payloads.
- Rights denial for `restricted` sources and enforcement for data-bearing files.
- Operator version conflicts become unsatisfied dependencies.
- Clean install into a fresh database with zero economic observations, followed by execution.
- Repeated install idempotence, integrity verification, exact-byte export, fork/compare,
  uninstall with retained research and execution history.
- Transaction rollback when object creation fails.
- A declarative domain pack install and uninstall.
- Migration from schema 9 with a verified backup and preserved user data.
- SDK scaffold, source test, package build and manifest inspection.
- HTTP base64 install, health counts, open, verify, execute, download, fork, compare and delete.

Run:

```bash
.venv/bin/python -m pytest -o addopts='' -q -p no:warnings tests/test_phase8_applications.py
```

The fixture package is tested by `scripts/build_phase8_fixtures.py`; the browser acceptance script
is `web/e2e/phase8.mjs`. A benchmark is not a correctness test, and a passing hash is not an
identity check.
