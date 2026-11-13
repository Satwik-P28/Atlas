# Phase 9.6.1 — Data Rights and Git History

## Confirmed exposure

`artifacts/phase9_6_evaluation.json` as committed in `d8ae4f1` contained 112 `question` and
`answer` fields copied verbatim from FinanceBench's `OPEN_SOURCE` subset (CC-BY-NC-4.0), while
`docs/PHASE9_6_DATASET_AND_RIGHTS_MANIFEST.md` stated that no such text was committed. That was a
data-handling defect and a false documentation claim.

## Data classification

| Class | Examples | Committed? |
| --- | --- | --- |
| Atlas-authored code and metadata | `src/**`, `scripts/**`, tests | yes |
| Public filing identifiers | accessions, CIKs, periods, EDGAR URLs | yes |
| Derived benchmark metrics | recall@k, ranks, counts, hashes | yes |
| Licensed benchmark text | FinanceBench questions, answers, evidence | **no** |
| Third-party document excerpts | short quoted passages with hashes | only in the case study artifact |
| Restricted source bytes | `var/*.db`, full filings | no (`var/` ignored) |

## Remediation performed

1. Sanitised `artifacts/phase9_6_evaluation.json` and `artifacts/phase9_6_case_study.json`: removed
   244 + 1 licensed fields, preserved every metric and every failed gate, and labelled the file a
   sanitised derivative of `d8ae4f1` at methodology 9.6.0.
2. New artifacts are sanitised at write time (`evaluation_v2.sanitize`); the full trace, including
   permitted local copies of question and answer text, goes to
   `var/phase9_6_1_eval_trace.json`, which lives under the ignored `var/` tree.
3. `tests/test_phase9_6_1_evaluation_contract.py::test_committed_artifacts_contain_no_prohibited_fields`
   fails the build if any committed artifact under `artifacts/` carries licensed text. `question`
   and `answer` are prohibited only in artifacts that declare a licensed dataset or Phase 9.6
   schema, because Atlas-authored Phase 9.5 questions are legitimately committed.
4. The rights manifest is corrected in `PHASE9_6_DATASET_AND_RIGHTS_MANIFEST.md` (see the erratum).

## History exposure assessment

Removing the text from `HEAD` does not remove it from Git history.

| Commit | Content | Refs |
| --- | --- | --- |
| `d8ae4f1` | adds the artifact with 112 question/answer pairs | branch `freebuff/0139b8fdada4bab1ac65bcfa` |
| `efb79c9` | adds the Phase 9.6 report; artifact unchanged | same branch |
| `486e7d0` (`main`) | not affected | `main`, `FETCH_HEAD` |

Consequences and options:

* **Normal cleanup commit (done):** prevents future leakage and makes `HEAD` compliant. It does
  **not** remove the blobs from `.git`, from the pushed branch, or from any clone/fork.
* **History rewrite (not done):** `git filter-repo`/BFG across `d8ae4f1..HEAD` would produce a new
  branch and require a force-push. This is explicitly not authorised in Phase 9.6.1, and the
  repository is private. Rewriting would also invalidate the recorded commit hashes in the
  Phase 9.6 report.
* **Exposure window:** the branch is private; no evidence of public disclosure exists. The licence
  (CC-BY-NC-4.0) permits non-commercial evaluation, and the repository is not distributed, so the
  current retention is a policy breach rather than a demonstrated licence violation — but that is
  a judgement for the repository owner, not something this phase can assert.

**Blocker:** until an authorised history rewrite (or an owner decision accepting the private
retention), release policy is not satisfied. Promotion to `main` is therefore refused.
