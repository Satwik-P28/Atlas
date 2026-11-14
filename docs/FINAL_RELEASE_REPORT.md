# Final release report — FOCUS checkpoint

**Date:** 2026-11-14
**Status:** `FOCUS_READY`, `PRIVATE_CANDIDATE_READY`, main promotion `BLOCKED_BY_HISTORY`
(and not authorised).

This report covers Phase A only. Phases B–D of the master brief (temporal evidence compiler
expansion, adversarial state machine, counterfactual replay, content-addressed caching, XBRL
corroboration, retrieval research) were **not implemented**. They are listed in section 9 as
outstanding work rather than described as progress.

---

## 1. GitHub state

| Item | Value |
| --- | --- |
| Remote `main` at fetch | `644448d4fbb3414c9c8045f5a86030ef34bfe2df` ("Restore main to the Phase 9.5 tree") |
| `main` tree | `af25770abc58c7ef86bcc628edf60c78953782dd` — byte-identical to the Phase 9.5 tree `486e7d0` |
| Base of this work | `616f131ffa5f19dad4ceee4b8f02ba874a497b57` ("Phase 9.6.4 candidate"), branch `release/9.6.4-candidate` |
| FOCUS implementation commit | `e86992eb516a3ea744dfafd0fe44e35e3047d3a7` |
| Release report commit | the commit that added this document: `git log -1 --format=%H -- docs/FINAL_RELEASE_REPORT.md` |
| Candidate tree | `7808b82e84bd01473e3751d4aefe32113742fef8` |
| Merge base (candidate, main) | `486e7d0fd4b01e7c402dff1d54b463c00aefa614` |
| Merge dry run | `git merge-tree --write-tree main HEAD` exits 0, no conflicts, result tree equals the candidate tree |
| Branch pushed | `focus/application-ready` |

Neither branch is an ancestor of the other: `main` was reverted to the Phase 9.5 tree after the
9.6 work, and the candidate continues from the 9.6.4 candidate. Promotion is a merge, not a
fast-forward.

### Discrepancy with the brief

The brief refers to PR #1 at `cursor/focus-priority0-827f`, HEAD
`1d11932402afb56583348101427972f4d57ad8b3`, and to files that PR was said to contain
(`src/atlas/research/certificate.py`, `src/atlas/research/certificate_verify.py`,
`scripts/reproduce_phase9_2.py` asserting schema 13, `make focus-demo`, `docs/FOCUS_*.md`).

That commit is **not present in this clone** and the branch does not exist locally. Discovery over
all local refs (`git log --all -- 'src/atlas/research/certificate*.py'`) returns no commits, so the
certificate layer did not exist on any branch available here. `git ls-remote` cannot run without
credentials in this environment, so the remote branch could not be independently checked.

The work in this branch was therefore built from the 9.6.4 candidate rather than repaired from a
missing PR. If PR #1 exists on the remote, it should be reconciled before promotion; this branch
does not claim to supersede it.

---

## 2. Engineering

### Defects found and fixed

1. **Stale schema assertion** (`scripts/reproduce_phase9_2.py`). Asserted `fresh_schema == 13`; the
   registry is at 15. Now asserts against `atlas.storage.migrations.LATEST_VERSION` and records
   `expected_schema`. No migration was edited and no financial assertion was relaxed.
2. **Answer packets did not record their operator** (`financial_answers._run`). Certificates were
   labelling `answer_type` (`reported_value`) as the operator. `operator` is now recorded and
   `build_certificate` rejects a packet without a supported operator.
3. **Scale declared inside the table was ignored** (`table_cells.extract_cells`). 3M prints
   `(Millions, except per share amounts)` as the table's first row; reading only the caption gave
   scale 0, recording 3M FY2022 net sales as **$34,229 instead of $34,229,000,000**. Header-row text
   now participates in scale detection.
4. **Refusal classification came from the resolver's status string** (`focus_cases`). 3M FY2018 was
   reported as `ambiguous_evidence` when the filing prints a unique consolidated `Net sales 32,765`;
   the 2017-cutoff case was reported as `capability_gap` instead of a historical refusal.
   Classification now inspects stored cells and document availability. This was a defect in
   *reporting*, and it is the kind of defect that manufactures a false research finding.

### New capabilities

- `src/atlas/research/certificate.py` — typed certificate payload, fingerprint, structural contract.
- `src/atlas/research/certificate_verify.py` — four verification levels, third independent
  arithmetic implementation, byte-level source authentication, pinned manifest builder.
- `src/atlas/research/focus_cases.py` — the thirteen cases, evidence-based outcome diagnosis.
- `scripts/focus_corpus.py` — pinned SEC ingestion with archived original bytes.
- `scripts/focus_demo.py` — the demonstration, including sixteen tamper mutations.
- `atlas certificate verify` CLI; `make focus-corpus|focus-cases|focus-demo|focus-manifest|focus-verify`.
- `tests/test_research_certificate.py` — 44 tests, 16 parametrised attacks.

### Remaining limitations

Currency is not detected for these statements. Concept mapping is a pinned judgement, not a
byte-provable fact. Extraction is trusted (the hash authenticates the document, not the parser).
Statement identity fails on 3M's FY2018 filing. See `docs/FOCUS_TECHNICAL_NOTE.md` §7.

---

## 3. Numerical correctness

Thirteen cases over four real 10-Ks. Ten answered, three refused.

| Case | Value | Scale | Economic amount | Level |
| --- | --- | --- | --- | --- |
| KO FY2022 revenue | 43,004 | 6 | 43,004,000,000 | `SOURCE_VERIFIED` |
| KO FY2022 net income | 9,571 | 6 | 9,571,000,000 | `SOURCE_VERIFIED` |
| KO revenue growth | 11.25 % | — | — | `SOURCE_VERIFIED` |
| KO operating margin | 25.37 % | — | — | `SOURCE_VERIFIED` |
| KO assets / revenue | 2.16 | — | — | `SOURCE_VERIFIED` |
| JPM FY2022 total assets | 3,665,743 | 6 | 3,665,743,000,000 | `SOURCE_VERIFIED` |
| JPM FY2022 net income | 37,676 | 6 | 37,676,000,000 | `SOURCE_VERIFIED` |
| JPM net income / assets | 0.01 | — | — | `SOURCE_VERIFIED` |
| 3M FY2022 net sales | 34,229 | 6 | 34,229,000,000 | `SOURCE_VERIFIED` |
| 3M net sales growth | −3.18 % | — | — | `SOURCE_VERIFIED` |

Independent checks by hand: 10,909 / 43,004 = 25.37 %; 92,843 / 43,004 = 2.16;
(43,004 − 38,655) / 38,655 = 11.25 %; (34,229 − 35,355) / 35,355 = −3.18 %.

Abstentions, by cause:

| Case | Classification | Basis |
| --- | --- | --- |
| JPM gross profit | `justified_unanswerability` | No verified statement row of this issuer uses the concept. |
| 3M FY2018 revenue | `capability_gap` | The filing prints `Net sales 32,765` for 2018; resolution failed to bind it. |
| 3M FY2022 at 2017 cutoff | `historical_information_refusal` | Accession 0000066740-23-000014 available 2023-02-08T18:14:49Z. |

Incorrect answers: **0 of the 10 answered cases**, checked against hand computation from the
filings. One refusal is a defect (case 12) and is reported as one.

---

## 4. Research

Hypothesis tested: a typed, source-bound computation with an independently verified certificate can
detect classes of error that untyped arithmetic and retrieval cannot.

Supported, narrowly: sixteen self-consistent forgeries of a certificate are refused; twelve of them
pass arithmetic-only verification, which quantifies exactly what the source evidence adds. The
historical-cutoff refusal demonstrates a temporal class that no amount of retrieval filtering alone
establishes.

Not supported / not tested: no baseline comparison against retrieval-only or an LLM was run, so no
claim is made that this approach answers *more* questions correctly. The case set is thirteen
curated questions written by the author; there is no benchmark, no FinanceBench score, and no
statistical uncertainty estimate that would survive review. These are the threats to validity.

Negative findings preserved: the scale defect, the resolver's misleading `ambiguous` label, the
absence of currency detection, statement-identity failure on the FY2018 filing, and the
undetectability of consistent forgeries without source evidence.

---

## 5. Performance

Machine: Linux container, Python 3.12.3, SQLite 3.45.1, NumPy 2.5.4, scikit-learn 1.9.1.

| Workload | Wall | Peak RSS |
| --- | --- | --- |
| `scripts/focus_demo.py` (13 cases, 10 certificates, 2 verifications each, 16 mutations) | 18.60 s | 89 MiB |
| Full backend suite (810 tests) | 150.96 s | not measured |

No optimisation was attempted and none is claimed. The dominant cost is re-extracting every table
of every document per call (`FinancialAnswerEngine.cells` is not memoised); this was measured, not
profiled, and no change was made because no measurement shows it matters for one document.

---

## 6. Testing

| Check | Result |
| --- | --- |
| Backend suite (`pytest`, 810 tests, `.[dev,terminal,learning,columnar]`) | **pass**, 150.96 s |
| New certificate suite (44 tests) | **pass** |
| `python -m compileall -q src scripts tests` | **pass** |
| `scripts/reproduce_phase9_2.py` (the previously failing CI step) | **pass**, `value_per_share` 295.4643539226478 |
| `scripts/phase9_6_4_case_studies.py` | **pass**, 10 answered / 3 abstained |
| `make focus-demo` | **pass**, 10 answered, 3 refused, 16/16 tampered refused |
| `atlas certificate verify` with evidence | `SOURCE_VERIFIED`, exit 0 |
| `atlas certificate verify` without evidence | `ARITHMETIC_VERIFIED`, exit 0 |
| Adversarial mutation matrix | 16/16 `INVALID` |
| Frontend tests / typecheck / build | **not run** — no `web/` changes were made and `npm ci` was not performed |
| Browser/Playwright acceptance | **not run** |
| GitHub Actions | **not refreshed** — Actions status cannot be queried from this environment; the failing step was reproduced and fixed locally |

Property-based, stateful, mutation (of the code), security and clean-install suites from the master
brief were not run beyond what is listed. The clean-install path used was `make install` in a fresh
`.venv` on this machine, not a fresh clone.

---

## 7. FOCUS readiness

- **Demonstration:** `make focus-corpus` (network) then `make focus-demo` (offline).
- **Technical note:** `docs/FOCUS_TECHNICAL_NOTE.md`.
- **Architecture:** `docs/FOCUS_ARCHITECTURE.md`.
- **Results:** `docs/FOCUS_RESEARCH_RESULTS.md`.
- **Application package:** `docs/FOCUS_APPLICATION_PACKAGE.md`.
- **Resume evidence:** `docs/RESUME_EVIDENCE.md`.
- **Interview defence:** `docs/ENGINEERING_DEFENSE.md`.
- **Source rights:** `docs/FOCUS_SOURCE_RIGHTS.md`.

Artifacts and SHA-256:

| Artifact | SHA-256 |
| --- | --- |
| `artifacts/focus_certificate.json` | `3484b0ab69ee6293090418b01ab0c8df213073ee9728214e3ac5d5fedd197aec` |
| `artifacts/focus_source_manifest.json` | `6c7638761667b3041417d699802d976736058cf1df3bd31ccdbd80f2c5bd39dd` |
| `artifacts/focus_corpus.json` | `624d49746cae9e6256eaae6eed6ed57dc1a299ca0f235e712fac79e049599d29` |
| `artifacts/focus_demo.json` | `763ba5ef3f794284bbf919dc5405f84c039a1aa86f1cdbc946bed9759d4f3525` |
| `artifacts/phase9_6_4_case_studies.json` | `36b7d45a73ec71208f556c95d4bdd59016419483dc1096f4647ae9f6f8571c5c` |
| `artifacts/phase9_2_reproduction.json` | `e8df3411503a8ded4b3e572329aecad63fed93845df83ca4efff38663c70153b` |

Screenshots: none were taken. No browser was driven. The deliverable is a terminal demonstration,
and saying otherwise would be false.

---

## 8. Release status

- `FOCUS_READY` — the Phase A deliverable is complete and reproducible on this machine.
- `PRIVATE_CANDIDATE_READY` — commit `e86992e`, tree `7808b82`, merges cleanly into `main`.
- `BLOCKED_BY_HISTORY` — `main`'s ancestry still contains `d8ae4f1`, which committed licensed
  FinanceBench material. The current tree is clean; the history is not. A merge does not sanitise
  ancestors.
- **Not promoted.** `main` is unchanged at `644448d`. Promotion requires an explicit decision on the
  history policy (retain private history with the licensing risk documented, or authorise a history
  rewrite) and explicit authorisation to push. Neither was given, so neither was done.

---

## 9. Outstanding work (Phases B–D, not started)

1. Temporal evidence contracts beyond the current binding: explicit `Flow`/`Stock` period typing and
   static rejection of future/segment/mixed-currency plans at plan-build time.
2. Property-based state machine over amendment, restatement, revision and cutoff (Hypothesis is
   installed and already used elsewhere; no new stateful tests were written).
3. Counterfactual replay comparing two cutoffs with deterministic change attribution.
4. Content-addressed dependency graph with invalidation and a measured cold/warm latency benchmark.
5. XBRL corroboration against SEC `companyfacts`, preserving conflicts.
6. Currency detection, which is the largest concrete correctness gap in the current results.
7. Baseline evaluation against retrieval-only, concept-resolver-only and untyped arithmetic on an
   identical question set — the experiment that would make a "this is better" claim defensible.
8. Frontend and browser acceptance, and a fresh-clone clean-install run.
