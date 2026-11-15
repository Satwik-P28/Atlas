# Phase 9.6.4 — Release Decision

## Decision: not released

The implementation is green (766 backend, 50 frontend, 23/23 browser) and produces ten
source-bound, independently verified real-filing answers, but the following remain open:

1. **FinanceBench reference rows are unavailable in this environment.** The 9.6.4 evaluator
   correctly exits 2 and records `unavailable_reference_data`; no new benchmark metric exists.
2. **XBRL corroboration is unimplemented** (no fact table in the corpus, no companyfacts adapter).
3. **Vintage policies are partial**: original-as-filed and conflict refusal exist;
   latest-at-cutoff, explicit accession and restatement comparison do not.
4. **Geometry is inference, not coordinate truth**: flattened arrays lose colspan/rowspan, so a
   same-count displaced row is undetectable; such cells are resolved only when counts agree.
5. **Repository history issue unchanged**: `main` remains `644448d` and the owner's decision about
   `d8ae4f1` in its ancestry is still open. No history rewrite, force-push or `main` update occurred.

## Recovery

The pre-repair dirty worktree was backed up to `var/recovery/9.6.4r/` with `manifest.sha256`
covering the three source modules, the new case-study script and artifact, and the pre-existing
Phase 9.1 audit modification (three `package_deterministic` model fingerprints, left untouched).

## Next

Provide the licensed FinanceBench rows out-of-band, implement the XBRL adapter, and add the three
missing vintage policies before a candidate is promoted.
