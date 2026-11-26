# Licensing

## Software licence: Apache-2.0, applied

Atlas-authored software is licensed under the **Apache License, Version 2.0**:

```text
Copyright 2026 Satwik Peddireddi

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

| Item | Where |
| --- | --- |
| Licence text (verbatim, unmodified) | [`LICENSE`](../LICENSE), reference copy at [`licenses/Apache-2.0.txt`](../licenses/Apache-2.0.txt) |
| Copyright and boundary notice | [`NOTICE`](../NOTICE) |
| Third-party attribution obligations | [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) |
| Dependency licence inventory | [`DEPENDENCY_LICENSES.json`](DEPENDENCY_LICENSES.json), [`DEPENDENCY_LICENSES.md`](DEPENDENCY_LICENSES.md) |
| Authorization and ownership verification | [`licenses/AUTHORIZATION-RECORD.md`](../licenses/AUTHORIZATION-RECORD.md) |
| Package metadata | `pyproject.toml`: `license = "Apache-2.0"`, `license-files` = LICENSE, NOTICE, THIRD_PARTY_NOTICES.md |

Why Apache-2.0: the explicit patent grant and patent-retaliation clause suit a quantitative and
decision-engineering codebase; it is permissive enough for research and commercial adoption; it
requires notices to be preserved; and it is compatible with every declared dependency, none of
which is copyleft in a shipped artifact.

## What the licence covers

- Atlas-authored source code in `src/`, `scripts/`, `tests/` and `benchmarks/`.
- Atlas-authored documentation and research reports.
- Project-authored synthetic fixtures under `fixtures/demo/**`, `fixtures/answer_semantics/**` and
  the synthetic market series under `fixtures/market/**`.
- The built frontend bundle, as far as it is Atlas-authored; bundled npm dependencies keep their
  own licences (see [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)).

## What it does not cover

Data rights are separate from software rights and are inventoried per source in
[`DATA_RIGHTS_INVENTORY.json`](DATA_RIGHTS_INVENTORY.json), discussed in
[`DATA_RIGHTS_AND_DISTRIBUTION.md`](DATA_RIGHTS_AND_DISTRIBUTION.md) and
[`DATA_LICENSING.md`](DATA_LICENSING.md).

- **SEC-derived financial facts** are stored as derived figures, identifiers, accession numbers,
  URLs and digests. Access and reuse follow SEC website terms; issuer-prepared filing content is
  not a U.S. Government work, so no public-domain claim is made over narrative text.
- **Synthetic market fixtures** are project-authored and covered by the software licence.
- **U.S. Government data** (Treasury, EIA, NOAA, FFIEC, FDIC) is treated as public domain with
  attribution retained.
- **Nasdaq and Alpha Vantage series** were committed before the Phase 9.2 rights remediation. They
  are removed from the tree, are redistributable under no terms Atlas possesses, and are excluded
  from every distributed artifact. They remain recoverable from the *development* repository's
  earlier history until the administrative remediation in
  [`PUBLIC_RELEASE_HANDOVER.md`](PUBLIC_RELEASE_HANDOVER.md) is executed; they are not present in
  the public distribution repository or in any release artifact.
- **Dependencies** keep their own licences. Listing a licence in an inventory is not a legal review.

## Verifying the licence in a built artifact

```bash
.venv/bin/python -c "import zipfile; z=zipfile.ZipFile('dist/atlas_quant-0.2.0b1-py3-none-any.whl'); print([n for n in z.namelist() if 'licen' in n.lower() or n.endswith('NOTICE') or 'NOTICES' in n])"
.venv/bin/python -c "from importlib.metadata import metadata; m=metadata('atlas-quant'); print(m['License-Expression'], m.get_all('License-File'))"
```

The wheel must report `Apache-2.0` and carry `LICENSE`, `NOTICE` and `THIRD_PARTY_NOTICES.md` in
its `.dist-info/licenses/` directory. `tests/test_release_safety.py` pins this.

## Documentation and content licence

The Apache-2.0 grant above applies to Atlas-authored documentation as well, which makes reuse,
translation and redistribution of the documentation lawful on the same terms as the code. The
project's own research claims remain subject to the limitations recorded in
[`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md); a licence is not a warranty of correctness.

## Trade marks

No trade mark or product-name right is granted. "Atlas" is used as the project name.

## Maintainer confirmations still open

1. **Employer/sponsor claim.** The repository cannot show whether an employer, client or funding
   agreement claims these contributions. The copyright holder must confirm this before any
   commercial redistribution.
2. **Contributions from others.** No third-party contributor commits exist in this repository. If
   outside contributions are accepted later, a contributor licence agreement or a Developer
   Certificate of Origin becomes necessary; [`CONTRIBUTING.md`](../CONTRIBUTING.md) records the
   current process.
