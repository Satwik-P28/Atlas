# FOCUS application package

## 100-word project description

Atlas is a point-in-time financial research system that turns SEC filing evidence into typed, independently verified computations. It resolves a research question to a specific statement cell, checks period, currency, scale, and historical availability, compiles the calculation through a financial compiler, and recomputes the result with a separate Fraction verifier. Accepted answers are packaged as research certificates that an independent CLI can validate. The system refuses ambiguous labels, unknown units, and evidence that post-dates the information cutoff. The FOCUS demonstration uses real Coca-Cola, JPMorgan, and 3M 10-K filings rather than synthetic data.

## 250-word explanation

Financial answers fail in practice when the wrong statement is cited, the scale is dropped, or a later restatement is treated as if it had always been available. Atlas attacks that failure mode directly. Filings are ingested from SEC EDGAR into a local store with availability timestamps. Tables are decomposed into cells that are either verified or explicitly unresolved. A concept resolver maps questions such as “3M FY2022 net sales” onto consolidated income-statement cells and refuses segment bridges and conflicting vintages. The selected cell is frozen into a binding so later arithmetic cannot silently re-search the corpus by row label. The Financial-Economic Compiler executes a typed plan; an independent verifier reparses the printed numbers with Fraction arithmetic; disagreement abstains. Results become `atlas.research_certificate.v1` objects with canonical fingerprints. `atlas verify-certificate` checks certificates without running the production answer pipeline. In the FOCUS demo, 3M’s FY2022 consolidated net sales resolves to printed 34,229 at scale 6 (USD millions). Tampering with the certified value fails verification, and the same binding under a 2017 cutoff is refused. Thirteen controlled real-filing cases across three issuers produced ten answers and three justified abstentions. The project does not claim trading performance, terminal parity, or a general FinanceBench leaderboard score without licensed reference rows.

## Full technical explanation

See `docs/FOCUS_TECHNICAL_NOTE.md` and `docs/FOCUS_ARCHITECTURE.md`.

## Nontechnical explanation

Atlas is software that reads company annual reports the way a careful analyst should: it checks which statement a number came from, whether that report was public on the date you care about, and whether the math still works when checked a second way. If it cannot be sure, it says so instead of guessing.

## Personal motivation prompts (for the owner)

Complete in your own voice:

1. Why did source identity become the central problem for you?
2. Which failure (wrong statement, wrong scale, lookahead) changed the design most?
3. What would you delete from Atlas before expanding it?

Do not invent anecdotes here.

## Difficult engineering questions

See `docs/ENGINEERING_DEFENSE.md`.

## Challenges encountered

- 3M prints “(Millions, except per share amounts)” inside the income statement table; treating missing scale as `0` produced a false economic amount until Priority 0 repaired detection.
- Bare alias `sales` over-matched segment and MD&A bridges; false-friend filtering was required.
- JPMorgan FY2022 filings are outside the SEC `recent` window; corpus builds must use the full submissions archive.
- `main` ancestry still includes historical FinanceBench material; clean FOCUS work is preserved on a candidate branch without force-pushing `main`.

## Failures that changed the design

- Success-conditioned evaluator denominators and a tautological assertion-precision formula were treated as correctness bugs, not reporting polish.
- Re-searching by row label after concept resolution was rejected in favour of bindings.
- Defaulting undetected scale to ones was rejected; unknown scale now leaves cells unresolved.
