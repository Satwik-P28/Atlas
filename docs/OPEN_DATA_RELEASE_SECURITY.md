# Open data release security

This is the review record for `.github/workflows/open-data-release.yml` after the
Phase III audit. It documents each finding, the change that fixes it, and how the
property is enforced rather than merely described.

Static properties are asserted by `tests/test_open_data_release.py`, so a future
edit that reintroduces shell interpolation, an unpinned action or broader
permissions fails CI.

## Findings and fixes

| # | Finding | Fix | Enforced by |
|---|---------|-----|-------------|
| 1 | `${{ github.event.inputs.* }}` interpolated inside `run:` shell | Inputs arrive only through `env:` (`ATLAS_RELEASE_*`) and are validated by `scripts/validate_release_inputs.py` into `dist/release-plan.json`; every later step reads the plan | `test_workflow_never_interpolates_inputs_into_a_shell` |
| 2 | Dataset ids, tags and filenames unvalidated | `atlas.open_data.release` validates against the registry and strict grammars (`DATASET_RE`, `TAG_RE`, `FILENAME_RE`) and rejects unknown, malformed, duplicate or non-redistributable ids | `test_unknown_and_unsafe_dataset_ids_are_rejected`, `test_release_tag_grammar`, `test_asset_filenames_must_belong_to_an_approved_dataset` |
| 3 | Oversized parameters unvalidated | `validate_oversized` requires `dataset=bytes`, an approved dataset, a numeric value above the 1.9 GB asset limit, and rejects duplicates | `test_oversized_claims_must_be_approved_and_above_the_limit` |
| 4 | Third-party actions referenced by mutable tags | `checkout@v4.2.2`, `setup-python@v5.6.0`, `upload-artifact@v4.6.2`, `download-artifact@v4.3.0`, each pinned to a reviewed commit SHA | `test_workflow_pins_actions_and_minimises_permissions` |
| 5 | Workflow-level `contents: write` | Workflow default is `contents: read`; `plan` and `package` are read-only; only `publish` holds `contents: write` | same test |
| 6 | Acquisition and publication in one privileged job | Split into `plan` → `package` (read-only) → `publish` (write, protected environment, human approval) | same test |
| 7 | Release published directly | `release_step.py draft` creates a **draft**; `release_step.py publish` flips it only when `mode: public` | `test_workflow_creates_a_draft_before_publishing` |
| 8 | Rights checked once, early | Re-validated in `plan`, at packaging time (per dataset `rights_decision`), and again immediately before upload | `scripts/build_release_packages.py`, `release_step.py` |
| 9 | Licence/attribution only in the external index | `build_open_data_package.py` embeds `LICENSES.md` and `LICENSES.json` inside every archive, from the current registry decision | `test_a_package_embeds_its_licence_terms` |
| 10 | Assets could be replaced in place | An existing tag aborts the run; the only correction path is a new tag (`open-data-YYYY-MM-rN`) | `draft()` in `scripts/release_step.py` |
| 11 | Failed runs left no record | `data/open_data/releases/publications/<stamp>-<status>.json` records draft, publish, failure and each verified API read; uploaded with `if: always()` | `write_publication_record` |
| 12 | Asset names unchecked before upload | `release_step.py check-assets` rejects oversized, unsafe or mismatched assets and verifies every sidecar hash | `check_assets()` |
| 13 | "Verified" meant an API read, never the bytes | `release_step.py verify` downloads every asset over HTTPS, hashes it, compares size, SHA-256 and the API digest, reconstructs multipart datasets and restores every package into a fresh store. `metadata_verified` and `byte_verified` are separate fields | `src/atlas/open_data/verification.py`, `test_release_verification_*` |
| 14 | A split period package was indexed under a container that was deleted | The index preserves the nested `split` and its sub-part hashes; the installer downloads the sub-parts and reassembles the container before use | `test_a_split_period_package_survives_the_index_and_installs` |
| 15 | Artifact uploads had several path roots, so a download could nest `dist/dist/...` | Each upload names one root and each download restores it to the directory the next job expects | `test_workflow_artifact_paths_are_single_rooted` |
| 16 | The protected environment was assumed, not checked | `scripts/check_release_environment.py` reads the real protection rules and fails the job unless required reviewers, self-review prevention and a `main` branch policy are configured | `test_publication_environment_must_require_reviewers` |
| 17 | Draft and promotion were one approval | Two protected jobs: `draft` creates and byte-verifies the draft; `publish` needs it, re-checks it without rebuilding, and only then flips the same tag public | `test_workflow_pins_actions_and_minimises_permissions` |

## What the workflow cannot do

* It cannot publish bytes for a dataset whose current registry decision denies
  public distribution: packaging, index generation and upload all re-evaluate the
  decision and the audit job runs `--strict` first.
* It cannot silently re-acquire a dataset with different bytes and call it the
  same release: the release index records the snapshot id and the source
  manifest hash, and a published snapshot is immutable in the store.
* It cannot upload a package larger than 1.9 GB: the size gate fails, and an
  oversized dataset must go through multipart packaging.

## Dispatching from this branch

GitHub requires a `workflow_dispatch` workflow to exist on the **default branch**
before the event can be dispatched (the UI lists default-branch workflows, and the
API refuses a ref whose workflow is not known to the default branch). This branch
is not merged, so the release cannot be dispatched from it, and it must not be
merged just to publish data.

The narrow bootstrap, if a maintainer chooses to use it, is a separate pull
request that adds **only** the release machinery to `main`:

```
.github/workflows/open-data-release.yml
scripts/validate_release_inputs.py
scripts/release_step.py
scripts/build_release_packages.py
scripts/build_open_data_package.py
scripts/build_open_data_multipart.py
scripts/index_open_data_release.py
scripts/build_open_data_registry.py
scripts/audit_open_data.py
src/atlas/                     (the open_data package the scripts import)
data/open_data/registry.json
data/open_data/manifests/     (the recovery contract the audit reads)
pyproject.toml
```

That PR carries no acquired data and no bulk bytes. After it is on `main`:

```bash
gh workflow run open-data-release.yml \
  -f datasets="sec.company_tickers treasury.nominal_yields" \
  -f tag=open-data-2026-11 -f mode=draft
```

Then approve the `open-data-release` environment, inspect the draft assets and
their `LICENSES.md`, and re-dispatch with `mode=public` (a new tag if anything
must change).

The `data/open-data-bootstrap` branch itself stays unmerged until the release
security, redistribution and recovery requirements are satisfied.

## Environment

`environment: open-data-release` in YAML is only a name. If the environment has
not been created, GitHub creates it on first use **without protection**, and the
`draft` and `publish` jobs then hold `contents: write` with no human gate. The
workflow therefore runs `scripts/check_release_environment.py` before creating or
publishing anything, and that script fails the job unless the live configuration
is protected.

Required repository configuration (Settings → Environments → `open-data-release`):

| Setting | Required value | Why |
|---------|----------------|-----|
| Required reviewers | at least one user or team | a human approves each of the two write jobs |
| Prevent self-review | enabled | the dispatcher cannot approve their own publication |
| Deployment branch policy | `main` only (or *Protected branches*) | a feature branch cannot reach the publication token |
| Wait timer | optional | a second look before the token is issued |

Branch protection for `main` (Settings → Branches): require a pull request with
at least one review, require the `CI` and `open-data validation` checks, disallow
force pushes and deletions, and do not allow bypassing for the release bot. The
only workflows that may run on `main` are the reviewed ones; `workflow_dispatch`
is limited to users with write access.

Verify the configuration from a machine with a repository-scoped token:

```bash
GH_TOKEN=... python scripts/check_release_environment.py --repo Satwik-P28/Atlas
# or inspect the raw rules
gh api repos/Satwik-P28/Atlas/environments/open-data-release | jq '.protection_rules'
```

The check is not a substitute for reviewing the draft: `draft` byte-verifies the
uploaded assets and records the outcome under
`data/open_data/releases/publications/`. The `publish` job is a second approval;
it re-reads the draft (`--metadata-only`) to prove that the reviewed tag and asset
set are the ones being promoted, and never rebuilds the release under a new tag.
