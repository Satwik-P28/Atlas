# Phase 9.6 — Citation and Entailment

## Three separate questions

| Level | Question | Who answers it | Phase 9.6 result |
| --- | --- | --- | --- |
| Citation integrity | Does the citation resolve to the correct, unmodified source span for this issuer? | machine | **1.0000 over 112 questions** |
| Evidence relevance | Is the passage relevant to the research question? | human, or a *validated* judge | not measured |
| Claim entailment | Does the passage support the claimed conclusion? | human, or a *validated* judge | not measured |

An intact SHA-256 proves only the first row. Atlas does not convert it into the second or third.

## What integrity actually checks

For every top-ranked passage the evaluator re-reads the stored body, recomputes SHA-256, compares
it with the stored digest, checks issuer identity and checks availability at the cutoff. A
corrupted passage, a substituted issuer or a future document fails this check. All 112 passed.

## Findings taxonomy

`build_document_claim` records a `statement_kind` (`verbatim_excerpt` or `abstention`) plus
`epistemic_status`, and the evaluator classifies retrieval failures as
`abstained_with_available_evidence`, `target_document_not_in_top_k` or
`answer_not_present_in_retrieved_passages`. These correspond to distinct epistemic outcomes; the
project's existing status vocabulary continues to separate:

* verified document quotation,
* source-supported factual statement,
* analyst interpretation,
* computed financial value,
* economically validated model conclusion.

## The policy split introduced in 9.6

The Phase 9.5 engine abstained whenever any query term was absent from the corpus. Measured on
independent questions, that veto rejected **91 of 112** answerable questions, mostly because of
instruction wording ("give a response", "FY2018"). It was replaced with two explicit policies:

* **balanced** (default retrieval): abstain only when nothing is retrievable. The analyst sees
  ranked evidence and decides.
* **strict** (claim construction): abstain when a content term is absent from the corpus or when
  the retrieved set covers less than 60% of the question's corpus-supplied terms.

Instruction vocabulary ("give", "response", "assume", "round") and years/units are excluded from
content terms, because their absence is evidence of nothing.

## Measured consequence

* Balanced retrieval: 0 false abstentions on 112 answerable questions (was 91).
* Strict policy on 10 self-authored negative questions: abstention recall **0.70** — below the
  pre-registered 0.80 gate.

The remaining failure mode is honest and stated: lexical signals cannot reliably distinguish
"the filing does not mention this topic" from "the question uses different words". A supervised
abstention model, calibrated on development negatives, is the correct next step; another
hand-tuned lexical threshold is not.

## Not claimed

* No LLM was used as ground-truth judge, and no entailment accuracy is reported.
* No independent human adjudication was performed in this phase.
* Numeric Research Integrity Engine behaviour and memo export restrictions were not weakened.
