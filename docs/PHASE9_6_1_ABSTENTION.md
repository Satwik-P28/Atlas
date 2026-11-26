# Phase 9.6.1 — Abstention

## Method

Two policies were compared on a development set before any holdout was touched:

* **term_absence** (the Phase 9.6 `strict` policy): abstain if any content term is absent from the
  corpus, or if the retrieved set covers < 60% of the question's corpus-supplied terms.
* **coverage**: abstain only on the coverage rule, ignoring absent terms.

Positives: the 112 independently annotated questions (answerable by construction).
Development negatives: 8 self-authored questions about topics no filing mentions (penguin
subsidiary, Antarctic mining, lunar depreciation, bitcoin rigs, Atlantis cable, series Z preferred,
zero-gravity division, teleportation segment).

Holdout: 8 further negatives authored at the same time but never inspected while choosing the
policy (orbital launch pad, dragon fruit division, volcanic ash provision, antarctic drilling
resignation, moon base pension trust, telepathic patent, underwater data centre, lithium unicorn
warrant). They were run once, after selection.

## Results

| Set | Policy | Precision | Recall | False abstention |
| --- | --- | --- | --- | --- |
| Development (8 negatives + 112 positives) | term_absence | 1.000 | 0.625 | 0.000 |
| Development | coverage | 1.000 | 0.250 | 0.000 |
| Holdout (8 negatives, negatives only) | term_absence (chosen) | n/a | 1.000 | n/a |

Selected on development by precision + recall: **term_absence**. Both policies have perfect
precision on this set: neither refused an answerable question, because strict search is only used
at claim construction, not at retrieval.

## Error taxonomy of the three development misses

The misses are all single-term gaps where the question's topic words exist in the corpus but in a
different sense:

* "submarine cable joint venture" — every content word appears in filings; the *combination* does
  not. Coverage clears 0.6, so the policy answers.
* "preferred series Z" — "preferred" and "series" are common; "Z" is dropped as a short token.
* "teleportation segment" — "segment" is everywhere, "teleportation" is absent; the absent-term
  rule should catch it, and lexical variants ("teleport") are not stemmed.

None of the negatives is mislabelled; none is answerable under different vocabulary. The failures
are the documented boundary of a bag-of-words test: it cannot represent "these words together, in
this relation, about this entity".

## Verdict

The pre-registered 9.6.1 gate (precision ≥ 0.80, recall ≥ 0.70, false abstention ≤ 0.10) **fails**
on recall (0.625). The 9.6.0 threshold of 0.80 recall was not changed to make the old benchmark
pass; this is a new policy version with its own numbers, and it still fails.

A calibrated support score (supervised, on a balanced development set with real hard negatives) is
the correct next step. Another hand-tuned lexical threshold is not, and was not added.
