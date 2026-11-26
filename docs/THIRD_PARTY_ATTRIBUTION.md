# Third-party attribution

Atlas ships two kinds of third-party material: Python packages the user installs around it, and
frontend packages compiled into the bundle inside the wheel. Both keep their own licences.

The machine-readable inventory is [`DEPENDENCY_LICENSES.json`](DEPENDENCY_LICENSES.json); the
generated summary is [`DEPENDENCY_LICENSES.md`](DEPENDENCY_LICENSES.md). Regenerate both with:

```bash
.venv/bin/python scripts/inventory_dependency_licenses.py
```

## Direct Python dependencies

Atlas declares its runtime dependencies in `pyproject.toml`. The inventory resolves each declared
name against installed metadata and records the licence the package reports about itself
(`License-Expression`, then `License`, then the trove classifier). Nothing is inferred from a
package name.

Every declared dependency declares a licence; the inventory's `missing licence metadata` count is
zero, which is a property of this environment and should be re-checked on any dependency upgrade.

## Frontend dependencies bundled into the wheel

The build compiles `web/` with Vite. Production dependencies are bundled and therefore require
their notices to travel with the wheel; development-only dependencies (200 of them) are not
shipped, and the inventory separates the two groups so a review can focus on what ships.

## Obligations to reproduce in a distribution

1. **MIT / BSD / ISC / Apache-2.0 dependencies** — reproduce the copyright notice and licence text.
   The generated inventory gives the licence per package; the texts come from the packages
   themselves in `node_modules/<package>/LICENSE*` and in installed Python distributions.
2. **MPL-2.0 dependencies** — file-level copyleft: publish the licence and make the source of the
   MPL-covered files available. Check `jspdf` and any other MPL entry in the inventory before
   publishing a bundle.
3. **Fonts and icons** — no web font is bundled by Atlas; the interface uses system font stacks.
4. **Python packages** — installed by the user, not vendored into the wheel, so their licences are
   satisfied by the package manager; the inventory exists so a reviewer can see what a user gets.

## What is not claimed

Listing a dependency's licence is not a legal review, and it does not relicense the dependency.
The Apache-2.0 licence applied to Atlas covers Atlas's code only; the effective attribution text
shipped with a distribution is [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
