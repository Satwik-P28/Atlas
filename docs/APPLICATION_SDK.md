# Application SDK

The SDK is a thin builder over the existing FEC compiler and package contracts. It does not
load application Python, JavaScript or shell and does not provide a plugin lifecycle.

## Scaffold

```bash
atlas app init ./my-app --name "Market cap example" --version 1.0.0
```

This writes `atlas.app.json` with schema `atlas.application_source.v1`, a declarative
`atlas.model.v1` model and a short README. The model uses the existing `mul` operator and
declares `price` and `shares` inputs. The generated application requests only
`execute_fec_operator` and `render_declarative_ui`.

## Validate, test, build

```bash
atlas app validate --file atlas.app.json --json
atlas app test --file atlas.app.json --json
atlas app build --file atlas.app.json --out dist/market-cap.atlas --json
atlas app inspect --package dist/market-cap.atlas
```

`validate` checks metadata and model compilation. `test` reports the compiled model fingerprint
and confirms that no executable plugin code exists. `build` produces a deterministic package with
`artifacts/model.json` and, when supplied, `artifacts/expected_outputs.json`.

`ApplicationBuilder` is the Python API. It provides `input`, `output`, `view`, `model`, `build`
and `document`. It derives operator versions from the compiled plan and refuses incomplete
applications. Programmatic builds use the same `build_package` function as the CLI, tests and
economic export.

## Source project files

`atlas.app.json` may list data files relative to the project. The loader rejects absolute paths,
`..`, and paths outside the project. Only the package format's declarative suffixes are accepted.
No file is executed; data files are included with explicit metadata only when a builder supplies it.
