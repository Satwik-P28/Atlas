# Verifying a release of Atlas

Three independent things can be checked without trusting the interface, the author or this
document: the downloaded files, the reproduction of a research answer, and the integrity of an
exported certificate. Every command below runs offline except where it says otherwise.

## 1. The downloaded files

```bash
sha256sum -c SHA256SUMS            # macOS: shasum -a 256 -c SHA256SUMS
```

All four assets must print `OK`. Compare the values against
[`RELEASE_GATES.json`](RELEASE_GATES.json) and the release page. A checksum is **not** a signature:
it proves the file you have is the file that was recorded, not who built it. No signing key or
attestation is claimed for this release.

Inspect the SBOM and the licence that travels with the wheel:

```bash
python - <<'PY'
import json, zipfile
print(json.load(open("sbom.cdx.json"))["metadata"]["component"]["name"])
z = zipfile.ZipFile("atlas_quant-0.2.0b2-py3-none-any.whl")
print([n for n in z.namelist() if "licenses/" in n])
print([l for l in z.read("atlas_quant-0.2.0b2.dist-info/METADATA").decode().splitlines()
       if l.startswith("License")])
PY
```

Expected: `atlas-quant`, three license members, and `License-Expression: Apache-2.0` followed by
three `License-File:` lines.

## 2. The install that the release was certified on

```bash
python -m venv .venv && . .venv/bin/activate
pip install "atlas-quant[terminal]==0.2.0b2"     # or the release wheel, after sha256sum -c
atlas --db var/atlas.db init && atlas --db var/atlas.db doctor
atlas demo --db-path var/demo.db        # offline, exit 0
atlas serve --db-path var/atlas.db --port 8000 &
curl -s http://127.0.0.1:8000/api/health | head -c 400
```

`doctor` reports schema version 15 and `integrity ok`; `demo` prints an end-to-end answer with its
evidence; the health endpoint returns 200 with `release_version`. The service is loopback-only and
unauthenticated — do not expose it.

From a checkout, `scripts/verify_packaged_install.py` repeats this inside a throwaway virtualenv and
fails nonzero if any step fails.

## 3. Scientific provenance: reproduce a real answer

This step needs network access to SEC EDGAR and a contact `User-Agent`, which SEC requires.

```bash
export ATLAS_SEC_USER_AGENT='YourName your@email'
python scripts/accept_real_filing_phase10_5.py
```

It fetches Apple's FY2026 10-K (accession `0000320193-26-000026`), ingests it, answers "total net
sales for 2026", cites the exact cell, recomputes the arithmetic independently, verifies the
certificate, records the availability contract, exports a memo and a PDF, checks MCP agreement, and
then repeats the whole journey on a second installation to prove the value, table hash and document
hash are identical. `artifacts/release/acceptance_real_filing.json` records all 45 steps and the
commit they ran against.

The certified result at commit `36c7ee8` was:

| Field | Value |
| --- | --- |
| Answer | 478,834 (USD millions, consolidated) |
| Source document SHA-256 | `f5480847e8c5394f04af46be31d9e8b1b290bc3838af3e2fb38133dd3d26aee7` |
| Source table SHA-256 | `616af41fb4570fc63d8a77ae9a10a63c31cfffe08e7fa7b836be5341f12f047d` |
| Availability | `precision=unknown`, `estimated=true`, `2026-11-03T13:20:15Z` |
| Citation quality | `exact` — the column label `2026` equals the resolved period |

A different value means either a different filing revision or a defect; both are worth reporting.
If SEC has since published an amended filing, the hashes will legitimately differ — say so rather
than calling it a failure.

## 4. Offline research reproduction

The FOCUS corpus pins a manifest over archived filing bytes and replays thirteen real filing cases,
then applies 29 self-consistent tampered certificates and requires every one to be rejected.

```bash
make focus-corpus      # network: archives four filings (needs ATLAS_SEC_USER_AGENT)
make focus-manifest    # writes the explicit trust anchor
make focus-demo        # offline: cases, certificates, mutations, refusals
make focus-verify CERT=artifacts/focus_demo/certificate.json
```

Result recorded for this release: 13 cases across Coca-Cola, JPMorgan and 3M — **10 answered, 3
refused**, each for a different reason, and all 29 tampered certificates rejected. A refusal that
happens to be correct is never counted as an answered question.

## 5. Certificate integrity

```bash
atlas verify-certificate --manifest artifacts/focus_source_manifest.json \
  --snapshots var/focus/snapshots --strict <certificate.json>
```

Four verification levels exist. `ARITHMETIC_VERIFIED` means the computation recomputes from the
cited operands and the source bytes are the pinned ones. It does **not** mean the economic
interpretation is correct; results carry `verified_but_not_proven_correct` for that reason.

## 6. Answer-quality claims

```bash
make semantics-report        # checks the report table against committed fixtures
make test                    # full offline suite
```

The development corpus (22 questions: 20/22 baseline, 22/22 geometry-aware) and the post-holdout
development cohort (47 questions: 36/47 baseline, 41/47 geometry-aware) are development results, not
an independent human evaluation, and the reports say so where the numbers appear.

## 7. What verification cannot show

- That the interface is usable: no external usability study has been run.
- That the interpretation is economically right: certificates prove internal consistency and source
  identity only.
- That the data is licensed for your use: see
  [`DATA_RIGHTS_INVENTORY.json`](DATA_RIGHTS_INVENTORY.json); the software licence does not cover
  third-party data.
- That the browser journey works on your browser: Chromium, Firefox and WebKit pass the 21-step
  journey in hosted CI; nothing else was tested.
