# FOCUS research results

## Hypothesis

If Atlas binds consolidated statement cells with explicit scale and availability, then:

1. Real multi-issuer filing questions can be answered with independently recomputed values.
2. Unsupported or historically unavailable questions abstain rather than invent answers.
3. A research certificate for an accepted answer verifies independently and fails under material mutation.

## Experimental setup

- Corpus builder: `scripts/focus_build_corpus.py` (SEC EDGAR 10-K HTML at build time).
- Issuers / accessions:
  - Coca-Cola `0000021344-23-000011`
  - JPMorgan `0000019617-23-000231`
  - 3M `0000066740-23-000014`
  - 3M `0001558370-19-000470` (FY2018 historical case)
- Case runner: `scripts/phase9_6_4_case_studies.py` (13 tasks).
- Flagship demo: `scripts/focus_demo.py`.
- Certificate tests: `tests/test_focus_certificate.py`.

No FinanceBench question text is stored in the repository. Population evaluator metrics are therefore not claimed here.

## Baselines

Prior Phase 9.6.4 artifacts reported ten answered / three abstained on a larger offline corpus, with 3M FY2022 net sales incorrectly carrying `scale=0`. That scale defect is treated as a negative finding that Priority 0 repairs.

## Dataset

Public SEC EDGAR filings only. Database files under `var/` are untracked. Manifest: `artifacts/focus_corpus_manifest.json`.

## Metrics

For the controlled case study (not a general accuracy benchmark):

| Metric | Value |
|--------|-------|
| Tasks | 13 |
| Answered | 10 |
| Abstained | 3 |
| 3M FY2022 scale | 6 (USD millions) |
| Certificate verify (unmodified) | valid |
| Certificate verify (value tamper) | invalid |
| Cutoff refusal (2017 for FY2022) | abstained |

## Results (re-run)

| Family | Issuer | Operator | Outcome | Value | Notes |
|--------|--------|----------|---------|-------|-------|
| operating | Coca-Cola | lookup revenue FY2022 | answered | 43004.00 | scale 6, raw 43,004 |
| operating | Coca-Cola | lookup net income FY2022 | answered | 9571.00 | scale 6 |
| operating | Coca-Cola | % change revenue 2022/2021 | answered | 11.25 | |
| operating | Coca-Cola | operating margin FY2022 | answered | 25.37 | |
| operating | Coca-Cola | assets/revenue FY2022 | answered | 2.1571 | ratio 4 dp |
| bank | JPMorgan | lookup total assets FY2022 | answered | 3665743.00 | scale 6 |
| bank | JPMorgan | lookup net income FY2022 | answered | 37676.00 | scale 6 |
| bank | JPMorgan | net income / assets | answered | 0.0103 | |
| bank | JPMorgan | lookup gross profit FY2022 | abstained | — | `not_found` (expected) |
| segment | 3M | lookup revenue FY2022 | answered | 34229.00 | scale 6 (repaired) |
| segment | 3M | % change revenue 2022/2021 | answered | -3.18 | |
| segment | 3M | lookup revenue FY2018 | abstained | — | `ambiguous` |
| cutoff | 3M | lookup revenue FY2022 @ 2017 | abstained | — | justified refusal |

## Failure cases / refusals

- JPMorgan gross profit: concept not present as a verified consolidated income concept in the ingested statement set.
- 3M FY2018 revenue: competing historical disclosures remain ambiguous under current resolution policy.
- Pre-availability cutoff: evidence after the cutoff is not used.

## Ablations

Not claimed. Priority 0 did not run a formal ablation tournament.

## Reproduction commands

```bash
export ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com'
python3 -m pip install -e ".[dev]"
python3 scripts/focus_build_corpus.py --db var/focus_demo.db
cp var/focus_demo.db var/phase9_6.db   # case-study script default path
python3 scripts/phase9_6_4_case_studies.py
make focus-demo
python3 -m atlas verify-certificate artifacts/focus_demo/certificate.json
python3 -m pytest -q tests/test_focus_certificate.py tests/test_phase9_6_4_evaluator_integrity.py
```

## Threats to validity

- Case studies are curated demonstrations, not a random holdout or FinanceBench score.
- HTML table geometry can still mis-align columns in pathological layouts.
- Alias-based concept resolution can abstain or err without XBRL tags.
- SEC network fetch at build time can fail or change primary-document names; accessions are pinned.
- Agreement between FEC and the Fraction verifier shows independent arithmetic consistency, not economic truth beyond the bound cells.
