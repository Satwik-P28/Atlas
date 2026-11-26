# Invitation preview — evaluation package

For up to ten invited users. **No participants have been recruited and no results exist.** Every
result recorded under this protocol is raw data from a named consenting participant; nothing here may
be filled in, estimated or illustrated with invented users.

## What a participant receives

1. The release wheel, its SHA-256 checksum and the source distribution for the same commit.
2. [`QUICKSTART.md`](../QUICKSTART.md) and the invitation note below.
3. A private feedback channel and an issue template.
4. A statement of what the software is (experimental preview) and what it is not (investment advice,
   institutional system, market-data terminal).

## Invitation note (send unchanged)

> You are invited to evaluate Atlas v0.2.0-beta.1, an experimental financial-research preview. It
> runs locally, needs no account and no API key, and includes a synthetic demonstration company so
> you can start without network access.
>
> Expected time: 45–60 minutes for the five tasks below. Please do not send us any confidential or
> licensed data; use the bundled synthetic filings and, if you want, one public company filing you
> fetch yourself.
>
> Participation is voluntary. You may stop at any time and ask us to delete your responses. We will
> publish aggregated results with your anonymised task outcomes only if you tick the consent box in
> the questionnaire. We will never publish your name, employer or free-text comments without asking.
>
> Atlas is not investment advice and makes no claim of guaranteed performance or hallucination-free
> output.

## Standardised tasks and expected outcomes

| # | Task | Expected outcome | What it measures |
| --- | --- | --- | --- |
| T1 | Install the wheel and run `atlas demo` | Terminal prints a loopback URL; browser shows the workstation | Installation success, time to first screen |
| T2 | Answer *gross profit, Atlas Demonstration Industries, 2023*, then build and verify a certificate | Value 21,690 with a citation; verification reports checks passed | Time to first useful result, comprehension of the citation |
| T3 | Ask for the same concept for 1999 | A refusal with a reason, no value | Understanding that refusal is a result |
| T4 | Export the memo as PDF, then run *Check for new evidence* | PDF downloads; change report says unchanged | Artifact comprehension, reproducibility expectation |
| T5 | Fetch one real company (`atlas sec sync --cik …`), ingest one filing, repeat T2 for a concept in that filing | A value with citation, or a refusal that names the missing evidence | Real-data task completion, interpretation accuracy |

Refusals are scored as correct outcomes when the evidence genuinely does not support an answer.
A participant who reports a confident wrong number is a finding about the product, not the person.

## Measurements

Record per participant: installation success (yes/no and the blocking error), minutes to first
useful result, per-task outcome (`completed` / `completed_with_help` / `refused_correctly` /
`incorrect` / `not_attempted`), whether they could explain the citation in their own words, whether
they could reproduce a value in a second session, and their stated trust (1–5) with the reason.

## Raw results schema

Store each session as one JSON object; never edit a submitted record afterwards.

```json
{
  "schema": "atlas.beta.session.v1",
  "participant": { "id": "P01", "consented_to_publish": true, "platform": "macOS 15 / Python 3.12" },
  "started_at": "2026-12-01T10:00:00Z",
  "install": { "success": true, "minutes": 4, "blocking_error": null },
  "tasks": [
    { "id": "T1", "outcome": "completed", "minutes": 3, "notes": "" },
    { "id": "T2", "outcome": "completed", "minutes": 6, "cited_correctly": true },
    { "id": "T3", "outcome": "refused_correctly", "minutes": 2, "notes": "expected a value" },
    { "id": "T4", "outcome": "completed", "minutes": 5, "pdf_opened": true },
    { "id": "T5", "outcome": "not_attempted", "reason": "no SEC contact identity" }
  ],
  "first_useful_result_minutes": 9,
  "evidence_comprehension": { "explained_citation": true, "reproduced_value": true },
  "trust": { "score": 3, "reason": "citation clear; unsure about availability bound" },
  "issues_filed": ["ISSUE-12"],
  "questionnaire": { }
}
```

Aggregate only from these files, and publish the aggregation script alongside the numbers so the
arithmetic can be checked.

## Questionnaire (send as a form)

1. Did the installation succeed on the first attempt? If not, what was the exact error?
2. In your own words, what does the citation on 21,690 tell you?
3. When Atlas refused the 1999 question, was the reason clear? What would you have expected instead?
4. Did any answer look right but turn out to be wrong? Describe it.
5. Could you reproduce a value in a new session? What did you compare?
6. What would you need before using this in real research?
7. What is the single most misleading thing about the product as presented?
8. May we publish your anonymised task outcomes? (yes / no)

## What this package must never contain

- Invented participants, invented timings or invented quotes.
- A "validation" label on development or post-holdout research results.
- Any claim that this preview has been externally validated. It has not been, yet.
