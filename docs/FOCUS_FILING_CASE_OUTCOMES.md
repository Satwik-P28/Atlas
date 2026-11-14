# Real-filing case outcomes (Priority 0 re-run)

Corpus: `scripts/focus_build_corpus.py` → `var/focus_demo.db` (copied to `var/phase9_6.db` for the case-study script).  
Runner: `scripts/phase9_6_4_case_studies.py`.  
Artifact: `artifacts/phase9_6_4_case_studies.json`.

Truth standard: accession, statement family/scope, concept, period, currency/scale, printed raw value, FEC result, independent Fraction check, cutoff behaviour. A correct number from the wrong statement is a **wrong-statement failure**.

| # | Issuer | Task | Outcome | Printed / value | Scale | Truth assessment |
|---|--------|------|---------|-----------------|-------|------------------|
| 1 | Coca-Cola | revenue FY2022 lookup | answered | 43,004 → 43004.00 | 6 | Pass — consolidated operating revenues |
| 2 | Coca-Cola | net income FY2022 | answered | 9,571 → 9571.00 | 6 | Pass |
| 3 | Coca-Cola | revenue % change 2022/2021 | answered | 11.25 | 6 | Pass — arithmetic on bound cells |
| 4 | Coca-Cola | operating margin FY2022 | answered | 25.37 | 6 | Pass |
| 5 | Coca-Cola | assets / revenue FY2022 | answered | 2.1571 | 6 | Pass — typed ratio precision |
| 6 | JPMorgan | total assets FY2022 | answered | 3,665,743 → 3665743.00 | 6 | Pass |
| 7 | JPMorgan | net income FY2022 | answered | 37,676 → 37676.00 | 6 | Pass |
| 8 | JPMorgan | NI / assets | answered | 0.0103 | 6 | Pass |
| 9 | JPMorgan | gross profit FY2022 | abstained `not_found` | — | — | Pass — correct refusal |
| 10 | 3M | revenue FY2022 | answered | 34,229 → 34229.00 | **6** | Pass — prior `scale=0` defect repaired; not a wrong-statement hit |
| 11 | 3M | revenue % change 2022/2021 | answered | -3.18 | 6 | Pass |
| 12 | 3M | revenue FY2018 | abstained `ambiguous` | — | — | Pass — competing disclosures refused |
| 13 | 3M | revenue FY2022 @ 2017 cutoff | abstained `not_found` | — | — | Pass — historical refusal |

**Summary:** 10 answered, 3 abstained, 0 wrong-statement failures observed in this re-run after the scale repair.
