# Licence authorization record — Apache-2.0 applied

**Status: applied.** The maintainer authorized Apache-2.0 for Atlas-authored software in the final
publication authorization of 2026-11-26, with the copyright holder line:

```text
Copyright 2026 Satwik Peddireddi
```

The grant covers original Atlas contributions for which the maintainer holds the necessary
rights. It does not extend to third-party datasets or third-party software.

## What was applied

| Item | Change |
| --- | --- |
| `LICENSE` (repository root) | Verbatim copy of `licenses/Apache-2.0.txt` — Apache License, Version 2.0, 11,358 bytes, SHA-256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`. Unmodified. |
| `NOTICE` (repository root) | Project name, copyright line, and the boundary between the software licence, third-party software and third-party data. |
| `THIRD_PARTY_NOTICES.md` (repository root) | Attribution obligations for the Python and bundled npm dependencies; states that data is not covered. |
| `pyproject.toml` | PEP 639 licence expression `license = "Apache-2.0"` and `license-files = ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"]`; project URLs; author metadata. |
| `CITATION.cff` | `license: Apache-2.0`, the copyright holder as author, and the release date. |
| `docs/LICENSING.md` | The decision record, replacing the earlier "not granted" status. |
| `licenses/NOTICE` | Removed: the effective notice is the root `NOTICE`, and two copies drift. |

`licenses/Apache-2.0.txt` stays as the verbatim reference text. Its hash is re-verified by
`tests/test_release_safety.py` against the root `LICENSE` on every test run.

## Ownership verification performed before applying

| Check | Result |
| --- | --- |
| Commit authorship in this repository | 153 of 153 commits reachable from the release commit are authored by `Satwik-P28 <astalavadios136@gmail.com>`; 4 commits in the wider development history are authored by `Cursor Agent <cursoragent@cursor.com>` (agent-assisted work performed for the same maintainer). No third-party contributor commits exist. |
| Vendored third-party source | None. `src/` contains no copied third-party implementation; dependencies are declared, not vendored. |
| Bundled fixtures | Project-authored synthetic filings or derived public-source facts; inventoried per path in `docs/DATA_RIGHTS_INVENTORY.json`. |
| Employer or sponsored-work claim | **Not verifiable from the repository.** The maintainer must confirm that no employer, client or funding agreement claims these contributions; recorded below as an open maintainer confirmation, not as a completed check. |
| Third-party datasets | Not licensed by this grant. Nine restricted vendor files remain in the development repository's history only and are excluded from every distributed artifact. |

## What this grant explicitly does not do

- It does not relicense any dependency; each keeps its own licence and notices.
- It does not grant rights over Nasdaq, Alpha Vantage or any other vendor data, nor over
  issuer-prepared filing text.
- It does not cure the historical exposure in the development repository. That requires the
  administrative remediation in `docs/PUBLIC_RELEASE_HANDOVER.md`.

## Consequence for the release gates

Applying the licence changed the wheel and sdist bytes, so every artifact hash recorded for phase
10.6 is superseded. The final hashes are the ones built after this commit and recorded in
`docs/RELEASE_GATES.json`; pre-licence hashes must not be published.
