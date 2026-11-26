# User testing protocol — Phase 9

## Status

**Not executed.** No external participants were available in this environment. No usability,
comprehension or trust claim is made for this release. This document is the protocol to run,
not a report of results.

## Participants

- At least three people who are not the implementer.
- At least one with professional financial-analysis experience and one without.
- Record role, prior tooling and whether they have seen Atlas before.

## Tasks

1. Starting from the terminal, find a company with valid financial coverage and one whose
   statements are incomplete. Explain the difference in your own words.
2. Open an issuer and identify why JPMorgan has no DCF value.
3. Explain what the independent component audit verifies and what it does not.
4. Find the share-count basis for a company and state its limitation.
5. Locate a missing input and confirm Atlas did not insert a zero.
6. Download, install and execute a research package; confirm the values reproduce.
7. Find a negative valuation and decide whether the interface makes the reason clear.

## Measures

- Task completion without assistance.
- Time on task.
- Misinterpretations, especially "the DCF is a forecast", "the value is a target price",
  "valid coverage means the model is valid".
- Whether the participant can locate provenance for a specific number.

## Rules

- Do not coach during the task; note where the interface required explanation.
- Do not count a task as passed because the tester found the number by accident.
- Record failures verbatim; do not rewrite them into successes.
- Report the number of participants and every failed task in the readiness record.

## Out of scope

Accessibility audit with assistive technology, localization and mobile-device testing have
not been performed and are not claimed.
