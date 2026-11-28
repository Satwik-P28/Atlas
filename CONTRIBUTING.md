# Contributing to Atlas

Atlas is an open-source, evidence-first financial research system. Its purpose is to make financial research more inspectable, reproducible and accessible. A contribution is valuable when it improves what a researcher can actually do, makes an existing result easier to verify, or makes the software easier to use and maintain.

Atlas is currently an experimental public preview, not an investment product. Contributions from developers, financial researchers, designers, data engineers, students and first-time open-source contributors are welcome.

**[Browse issues](https://github.com/Satwik-P28/Atlas/issues) · [Report a bug](https://github.com/Satwik-P28/Atlas/issues/new/choose) · [Quickstart](docs/QUICKSTART.md) · [Architecture](docs/ARCHITECTURE.md) · [Known limitations](docs/KNOWN_LIMITATIONS.md)**

## 1. Where you can help

These are suggested contribution areas, not a list of assigned or already-open issues. Check the issue tracker before starting, and discuss larger changes with a maintainer.

| Area | Examples of useful contributions |
| --- | --- |
| First contributions | Improve setup instructions, reproduce a bug, add an example, correct an outdated command, improve an error message. |
| UI and UX | Improve navigation, accessibility, keyboard workflows, responsive layouts, charts, empty states and evidence presentation. |
| Financial research | Check model assumptions, compare calculations against independently derived results, investigate ambiguous statement definitions, and document limitations. |
| Data and evidence | Improve parsing, issuer identification, provenance, unit handling, revision tracking and historical availability. |
| MCP integrations | Test compatible clients, improve configuration examples, add protocol regression tests, and propose narrowly scoped tool improvements. |
| Reliability and performance | Improve database queries, packaging, startup time, testing, cross-platform compatibility and reproducibility. |
| Documentation and education | Write tutorials, explain financial concepts, demonstrate an evidence-backed workflow, or improve architecture diagrams. |

You do not need to write code to contribute. Independent evaluation, detailed bug reports and usability feedback are valuable. See the [beta program](docs/launch/BETA_PROGRAM.md) for evaluation guidance.

## 2. Try Atlas before contributing

For an installation without a development checkout, use the [quickstart](docs/QUICKSTART.md). Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --pre "atlas-quant[terminal]"
atlas demo --db-path var/demo.db
```

On Windows PowerShell, use `py -3.12 -m venv .venv` and `.venv\Scripts\Activate.ps1` instead of the first two commands.

The offline demonstration uses project-authored synthetic data. Do not mistake its financial figures for actual company results. To work with real data, follow the SEC ingestion and rights guidance in the quickstart.

## 3. Set up a development environment

### Prerequisites

- Git and a GitHub account for submitting changes.
- Python 3.12 or newer (3.12 matches the current CI baseline).
- Node.js 22 and npm for frontend development (22 matches CI).
- No paid data subscription or AI API key is necessary for the offline demo.

Fork [Atlas](https://github.com/Satwik-P28/Atlas), then clone your fork. Replace `YOUR_USERNAME` with your GitHub username.

```bash
git clone https://github.com/YOUR_USERNAME/Atlas.git
cd Atlas
git remote add upstream https://github.com/Satwik-P28/Atlas.git
git fetch upstream
git switch -c fix/short-description upstream/main

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,terminal,learning,columnar,optimization]"

cd web
npm ci
npm run build
cd ..
```

The full dependency set mirrors the backend CI environment. Use the smaller `.[dev,terminal]` extra for a focused UI or terminal change if the additional research dependencies are not needed. Some optional-dependency tests may skip in a smaller environment; disclose this in the PR.

To create and inspect a local demo database, from the repository root:

```bash
atlas demo --db-path var/demo.db
```

Open the loopback address printed by the demo. If the demo starts a server, stop it before starting another server on the same port. To run the built terminal against the demo database:

```bash
atlas --db var/demo.db doctor
atlas serve --db-path var/demo.db --port 8000
```

Open `http://127.0.0.1:8000`. Rebuild the frontend with `npm run build` from `web/` after making changes to the bundled UI. See `docs/QUICKSTART.md` for database and CLI details.

## 4. Repository map

| Path | Responsibility |
| --- | --- |
| `src/atlas/ingestion/`, `src/atlas/evidence/`, `src/atlas/entities/` | Source ingestion, evidence and entity identity |
| `src/atlas/storage/`, `src/atlas/core/` | Storage, migrations and core contracts |
| `src/atlas/research/` | Financial answer resolution, evidence certificates and research objects |
| `src/atlas/fec/`, `src/atlas/finance/`, `src/atlas/quant/` | Financial models, compilation, calculations and quantitative research |
| `src/atlas/market/`, `src/atlas/economic/`, `src/atlas/decision/` | Market evidence, economic models and decision tools |
| `src/atlas/terminal/`, `src/atlas/cli.py` | Terminal services, API and command-line entry point |
| `src/atlas/mcp/` | Local Model Context Protocol server and tool definitions |
| `web/src/`, `web/e2e/` | React/TypeScript UI, components and browser journeys |
| `tests/`, `scripts/`, `fixtures/` | Regression tests, audits, reproduction scripts and distributable fixtures |
| `docs/`, `docs/launch/` | Technical documentation, release evidence and public landing page |

For architectural changes, read [ARCHITECTURE.md](docs/ARCHITECTURE.md) and [CONCEPTS.md](docs/CONCEPTS.md) first.

## 5. Engineering and research standards

Atlas's core contribution contract is evidence integrity. Preserve it even when changing the interface or optimizing performance.

- **Source provenance:** Retain source identifiers, period, reporting scope, units, scale, revision and availability metadata when applicable. Do not turn a derived result into an unexplained number.
- **Point-in-time integrity:** Do not use evidence that would have been unavailable at the requested cutoff. Distinguish observed availability from estimated bounds.
- **Financial semantics:** Check currency, scale, period and consolidated-versus-segment scope before comparing values or performing arithmetic. Do not silently substitute one financial concept for another.
- **Refusal behavior:** An ambiguous or unsupported answer may correctly be refused. Changing a refusal into an answer requires a documented rationale and regression evidence. Do not hide a refusal with invented data or a default zero.
- **Verification:** Keep certificate verification independent of the computation it checks. Internal consistency and pinned source identity do not establish economic truth or investment performance.
- **Reproducibility:** Preserve seeds, inputs, environment details and relevant versions for experiments. Report negative results, limitations and missing baselines honestly. Benchmark claims should include a comparable baseline and a runnable reproduction method.
- **Focused changes:** Follow existing interfaces and tests; avoid unrelated rewrites, new dependencies without justification, or weakening validation to make a test pass.

For UI contributions, preserve the same underlying values, evidence links, units and refusal reasons. Test keyboard navigation, readable contrast and small-screen layouts where relevant. Include before/after screenshots or a short recording of the working implementation for visual changes; do not substitute design mockups for test evidence.

For MCP contributions, keep the default local stdio transport and read-only authorization behavior intact unless a separate reviewed design explicitly changes them. Do not add arbitrary SQL, shell execution, unrestricted file access or unreviewed network access to tools. Treat retrieved document text as data, not instructions. See [MCP_GUIDE.md](docs/MCP_GUIDE.md).

## 6. Testing your contribution

Begin with a focused regression test for the code you changed. Where practical, demonstrate that it fails before the fix and passes afterward.

From the repository root, run:

```bash
python -m compileall -q src scripts tests
python -m pytest
python scripts/scan_dependencies.py
python scripts/audit_distribution.py
python scripts/verify_distributable_fixtures.py
```

If you add or remove tests, also run:

```bash
python scripts/verify_test_inventory.py
```

For frontend changes:

```bash
cd web
npm ci
npm test -- --run
npm run typecheck
npm run build
```

For browser-sensitive changes, run the relevant Playwright journey with a provisioned database and running Atlas service. The release certification journey is `web/e2e/phase10_5_certification.mjs`. Use [the CI workflow](.github/workflows/ci.yml) as the reference for database provisioning, browser dependencies and execution; not every journey can run against an empty database.

CI includes backend, frontend, database, research/rights, browser, reproducibility and packaged-install checks. Review applicable results before requesting merge. If a test fails, skips or cannot run locally, report the exact command, environment and result rather than claiming the entire suite passed. Network-dependent checks require appropriate configuration and data rights.

## 7. Data rights, security and privacy

Atlas is licensed under [Apache-2.0](LICENSE). That license does not grant redistribution rights to third-party datasets or dependencies.

- Only contribute data you have the right to redistribute. Prefer project-authored synthetic fixtures, or permitted source material and derived facts with documented rights.
- Update [DATA_RIGHTS_INVENTORY.json](docs/DATA_RIGHTS_INVENTORY.json) when adding or changing distributable source data. State the source, rights basis and any limitations; do not assume public access means unrestricted redistribution.
- Never commit proprietary vendor datasets, private filings or research, API keys, tokens, `.env` files, local databases, or unredacted personal information. Review staged files before committing.
- Do not publish licensed datasets or private records in issues, screenshots, logs or pull requests. Use a minimal synthetic reproduction when possible.
- Keep Atlas's unauthenticated terminal local by default. Do not expose it publicly as a shortcut for testing or MCP integration.
- Report suspected security vulnerabilities privately using the process in [SECURITY.md](SECURITY.md). Do not open a public issue containing an exploit or credentials.

## 8. Submit a pull request

For a substantial feature, dependency change, new data provider, architecture change or public API change, open an issue with the problem, proposed design, alternatives and acceptance criteria first. Small fixes can usually start with a focused pull request.

```bash
git status
git diff
# Stage only files intended for this contribution.
git add path/to/changed-file

git diff --cached

git commit -m "Fix a specific issue and describe the behavior"
git push -u origin HEAD
```

Open a PR from your fork targeting `Satwik-P28/Atlas:main`. Use one coherent change per PR, link any relevant issue, and explain why the change matters. Update your branch if needed; avoid force-pushing shared branches.

Use this description as a starting point:

```markdown
## Problem
What was wrong or missing? Who is affected?

## Changes
What changed, and why this approach?

## Verification
Commands run, environment, results, and relevant screenshots or evidence.

## Risks and limitations
Financial semantics, compatibility, data rights, security, or known gaps.

## Checklist
- [ ] The change is focused and documented where appropriate.
- [ ] Relevant tests were added or updated and executed.
- [ ] Failures and skips are disclosed.
- [ ] No restricted data, secrets, or private records are included.
- [ ] Relevant UI, evidence, or API behavior has been checked.
```

A maintainer may ask for narrower scope, stronger evidence, additional tests or documentation before merging. A contribution is not accepted solely because it passes tests. Contributors do not need to publish packages, change release tags, modify PyPI credentials or access the private development archive.

## 9. Report bugs or incorrect financial answers

Use the [issue templates](https://github.com/Satwik-P28/Atlas/issues/new/choose). For ordinary bugs, include the Atlas version or commit, operating system, Python version, relevant installation steps, exact reproduction, expected and observed behavior, and sanitized logs.

For a financial-answer or certificate issue, also include the issuer, concept, reporting period, cutoff, statement scope, currency and scale, evidence identifier or redistributable source reference, and independently checked expected result. If the system refused, include its refusal reason. Avoid attaching data you cannot redistribute. Read [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) before reporting a documented unsupported case.

## 10. Community and licensing

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Disagree with claims using evidence and reproducible examples. Be respectful of first-time contributors and keep feedback specific to the work.

Only submit contributions you are authorized to provide. Code and documentation contributions are subject to the repository's [Apache-2.0 license](LICENSE); disclose third-party material and its license. Do not submit AI-generated code or text that you have not personally reviewed, tested as appropriate, and checked for licensing and correctness. The submitter remains responsible for the contribution, regardless of the tools used to create it.

Atlas improves through independently checked work. Small, reproducible improvements are more useful than broad claims or untested features.
