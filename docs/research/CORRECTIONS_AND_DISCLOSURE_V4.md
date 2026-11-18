# Corrections and disclosures, fifth pass

Append-only continuation of `CORRECTIONS_AND_DISCLOSURE_V3.md` (which followed `_V2`). Both are left
unedited; this file records what the review of `f48e53b` found and what changed.

The four findings have one theme: each is a place where the code produced a plausible number for a
question that had not actually been settled. Identity was collapsed, semantics were summed across
incompatible bases, a tolerance comparison was called a guarantee, and a timestamp was treated as an
incorporation record.

## 1. Duplicate revision identities were counted twice — P0, correctness

`supplied_ids` and `by_id` collapsed duplicates into a set and a dict, but the application loop
iterated the *original* list, so two records sharing one `revision_id` each contributed their delta.
One immutable event could therefore be added twice — the exact double count the module exists to
prevent — with no error, no warning and a lineage record listing the id once.

**Now.** Duplicates are refused at the top of `compile_revisions`, before any map is built or any
correction applied. The report is deterministic: duplicate ids sorted, differing field names sorted,
`identical_payload` stated per id, and the error message distinguishes an identical repeat ("the same
immutable event was supplied more than once") from conflicting payloads ("one immutable id cannot
describe two different events"). A duplicate or conflicting `InputSensitivity` for one input is
refused the same way; the old code kept the last declaration silently, which changed the arithmetic
without changing the record.

**Tests.** `tests/test_decision_identity.py`: identical duplicate, conflicting duplicate with the
field named, duplicate across different inputs, duplicate inside a supersession chain, and order
independence of the report (both orders produce the same message and the same context).

## 2. Absolute and incremental deltas were summed across different bases — P1, semantics

The compiler refused two absolutes for one input but permitted one absolute plus any number of
increments, adding every delta in publication order. `+0.002` incremental followed by an absolute
correction of `0.005` produced `0.007`, although the documented meaning of an absolute delta is "the
corrected value". The sum was not wrong arithmetic; it was arithmetic on a question that had no
defined answer.

**Now.** `delta` is defined once, for every revision type, in the module constant `DELTA_SEMANTICS`:

* `incremental` — an addition to the input's value on top of the frozen baseline and the other
  applied increments; composition is addition, hence order-independent (asserted by test).
* `absolute` — the total correction for the input relative to the frozen baseline at
  `starting_vintage`. It replaces rather than composes, so exactly one may be operative per input,
  and the baseline must be named: an operative absolute revision without `starting_vintage` is
  refused. "The corrected value" with no reference is not a number the model defines.

A mixture on one input is refused with the input key and both revision ids. Increments may share an
input freely; absolutes may not share it at all. The inference rule is unchanged (absolute when a
revision supersedes or is superseded), so a chain still resolves to one operative version — now with
the baseline recorded.

**Tests.** Increment composition and order-independence, lone absolute as total correction,
absolute+increment refusal, two-absolutes refusal, missing-baseline refusal, absolute on one input
composing with an increment on another, and a correction replaced by an absolute successor (only the
successor applied).

## 3. `1.000` resolution-aware soundness was read as a certified bound — P1, claims

The emitted margin is a forward-error *estimate*; `verification_resolution` is the spread between two
float64 solvers, which is not a bound on their shared error. Calling the resulting rate `1.000` "the
guarantee" claimed more than either number supports.

**Now.** Three statements are separated, in the certificate (`claims.made`, `claims.not_made`, with
the assumptions of each) and in the report:

| Claim | Status |
|---|---|
| Analytic regret bound under exact arithmetic | **made** — weak duality, conditional on the declared program and sensitivity |
| Empirical agreement with an independent solver | **made** — to a stated resolution, as an observation |
| Verified floating-point enclosure | **not available** — no directed rounding or interval arithmetic was implemented |

`0.941` strict stays visible beside `1.000` resolution-aware. Neither is described as exact.

**A stronger reference was attempted, and it settles more than the rate.** A solver's objective is an
admissible measurement of the optimum only if its point is feasible, so the lower point of each event
is repaired onto the feasible set by bisection toward the recorded decision (feasible by construction;
the feasible set is convex, so the segment crosses the boundary once). All 598 events produced a
feasible point: 588 already feasible at `1e-13`, 10 needing up to 60 steps. Measured from that point,
regret exceeds the algebraic bound outright in **105** events and beyond the resolution in **0**;
smallest margin `-3.2e-16`. The outright excesses are the honest limit of the method, not a defect:
the bound is of order `1e-19` while measuring regret subtracts two objectives of order one, which
float64 resolves to about `1e-16`. **The bound is smaller than the arithmetic's ability to measure
it.** The empirical work therefore supports "the reference does not contradict the bound"; the
verdict itself rests on the analytic identity. This is weaker than the previous revision's framing and
stronger than no check at all, and it is what the numbers say.

## 4. `starting_vintage` was recorded but not checked — P2, historical integrity

The pre-decision guard excluded every correction that was public and economically effective before the
decision clock, treating "public" as "incorporated". A frozen source vintage can omit a document that
was already public, so the guard silently assumed the very fact it was supposed to audit.

**Now.** `EvidenceRevision.incorporation` distinguishes three cases, and the compilation reports which
one it used:

| Status | Effect |
|---|---|
| `documented_incorporated` (+ `incorporated_in`) | excluded as a documented double count; an `incorporated_in` that contradicts `starting_vintage` is refused |
| `documented_excluded` | applied, and reported as a base-model omission rather than a double count |
| `unknown` (default) | excluded, with `incorporation: "assumed"`, the ids named, and `incorporation.assumption` written into the compilation record |

The historical claim is now only as strong as the record behind it. "The base vintage already
contained this" is documented; "the model missed a public document" is documented; "we assumed the
base vintage contained it" is labelled as an assumption.

**Tests.** Assumed status with the assumption recorded, documented incorporation excluded with its
vintage, documented omission applied, contradictory vintage refused, unknown status refused at
construction.

## 5. Superseded results preserved

| Artifact statement | At `f48e53b` | Now |
|---|---|---|
| Two records with one `revision_id` | applied twice | refused before any arithmetic |
| Absolute + incremental on one input | summed (`0.002 + 0.005 = 0.007`) | refused |
| Absolute delta without a baseline | accepted | refused; `starting_vintage` required |
| Duplicate sensitivity for one input | last one kept silently | refused |
| "Resolution-aware soundness = 1.000" | presented as the guarantee | empirical agreement only; `0.941` strict kept beside it |
| Verified floating-point enclosure | implied by the wording | explicitly **not available** |
| Public-before-decision | treated as incorporated | documented / documented-absent / assumed, and labelled |
| Test count | 933 | 955 (193 in the decision layer) |

Unchanged by this pass: the certified rate (`0.413`, interval `[0.373, 0.453]`), the tightness curve,
the analytic bound (`1.77e-17` max algebraic, `4.29e-17` max emitted), the 35/598 strict exceedances,
the identity residual in extended precision (`2.07e-18`), the SEC case verdict and bound
(`2.35e-16`), and every experiment's configuration.
