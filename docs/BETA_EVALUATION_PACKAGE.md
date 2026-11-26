# External beta evaluation package

**Status: prepared, NOT RUN.** No external participant has executed this protocol. No usability,
comprehension, trust or installation-success result is claimed for v0.2.0-beta.1. This document is
the complete package a facilitator needs; the machine-readable results schema is
[beta_eval_results.schema.json](beta_eval_results.schema.json).

This supersedes the install instructions in `ATLAS_BETA_USER_TEST_PLAN.md`, which assumed a source
checkout with Node. The release wheel needs neither.

## Participants

Recruit three to five, at least:

- one financial analyst or experienced finance researcher;
- one finance student or investment-club participant;
- one technically competent person who has never seen Atlas.

Record role, years of relevant experience, prior tools, and whether they have seen Atlas before.
Participants must not be involved in building it.

## Session shape (60–75 minutes, think-aloud)

| Phase | Minutes | Activity |
|---|---|---|
| Setup | 5 | Consent, recording permission, machine check |
| Install | 10–15 | Unassisted install from the release wheel |
| Task sheet | 30–40 | Five tasks below, think-aloud, facilitator intervenes only to unblock a dead end (counted) |
| Debrief | 10 | Questionnaire and open discussion |

Facilitator rules: do not teach the interface. If the participant is stuck for more than three minutes,
note the intervention and give the minimum hint needed. Record every intervention.

## Participant instructions (read verbatim)

> You are evaluating a research tool called Atlas. It is a pre-release research system, not a
> financial product, and some features are deliberately absent. There are no wrong answers about the
> tool: if something is confusing, that is a finding and not your mistake. Please think aloud as you
> work. I will not help unless you are completely blocked, and I will note if I do. You may stop at
> any time and ask for your recording to be deleted.

## Task sheet

Each task states the goal, the pass condition and what is measured. Do not read the pass conditions
aloud.

**T1 — Install and first run.**
Install Atlas from the provided artifact, create a database, run the diagnostics command and the
offline demonstration.
*Pass:* demonstration completes without editing code or setting undocumented environment variables.
*Measure:* time to completion, number of facilitator interventions, errors encountered.

**T2 — Find a financial fact and its evidence.**
Using the demonstration database, find a company's reported figure for a period you choose and locate
the exact filing cell or passage behind it.
*Pass:* participant reaches the evidence view and can say which document and period the number comes
from.
*Measure:* success, time, whether they noticed the scale/units, confusion points.

**T3 — Recognise synthetic versus real data.**
Determine whether the price data in front of you is observed market data or a synthetic fixture.
*Pass:* participant states it is synthetic and can point to where the tool says so.
*Measure:* success, confidence, whether the distinction was understood or merely repeated.

**T4 — Understand a refusal.**
Ask a question Atlas refuses (a definitional ambiguity or a scope mismatch) and explain in their own
words why it refused and what would make it answerable.
*Pass:* participant identifies the reason as ambiguity/scope rather than "the tool is broken".
*Measure:* success, whether refusal increased or decreased trust, quote.

**T5 — Reproduce a research result.**
Install a research package, execute it, and confirm the outputs reproduce; then export it and verify
its integrity.
*Pass:* participant reports reproduction success or explains the mismatch precisely.
*Measure:* success, time, understanding of what "reproduced" means.

## Evaluation rubric

Score each dimension 1–4 after the session. Anchor descriptions, not adjectives:

| Dimension | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| Installation success | Did not complete | Completed with >2 interventions | Completed with ≤2 interventions | Completed unaided |
| Time to first useful result | >30 min or not reached | 15–30 min | 8–15 min | <8 min |
| Evidence location (T2) | Could not find the source | Found with help | Found unaided, imprecise about period | Found unaided, stated document, period and units |
| Synthetic/real distinction (T3) | Wrong belief | Repeated a label without understanding | Correct with reasoning | Correct and identified the consequence for use |
| Refusal comprehension (T4) | Read as failure | Partial reason | Correct reason | Correct reason and what would make it answerable |
| Research reproduction (T5) | Failed | Succeeded with help | Succeeded unaided | Succeeded and explained what was verified |
| Interface coherence | Repeatedly lost | Frequent confusion | Occasional confusion | Coherent navigation throughout |
| Perceived utility | Would not use | Unsure | Would use for some tasks | Would use in place of current practice for a named task |

Also record verbatim: the single most confusing moment, the single most valuable capability, and any
claim the participant believed that the tool does not support.

## Feedback questionnaire (post-session)

Answer on a 1–5 scale (1 strongly disagree, 5 strongly agree), then free text:

1. I could install and start Atlas without help.
2. I could find the evidence behind a financial number.
3. I understood when Atlas was refusing to answer, and why.
4. I could tell synthetic data from real data.
5. I understood what Atlas verified and what it did not.
6. I could reproduce a research result.
7. I would trust an Atlas answer more than a spreadsheet cell with no source.
8. I would use Atlas for a real research task this month.
9. The interface felt coherent rather than like separate tools.
10. The documentation answered my questions.

Free text: what did you expect that was missing; what did you believe that was wrong; what would you
remove; would you recommend it to a colleague, and for what task.

## Defect report template

```text
id:            BETA-<participant>-<n>
task:          T1..T5 | free exploration
severity:      blocker | major | minor | cosmetic
category:      install | evidence | refusal | data-label | reproduction | navigation | documentation
observed:      what happened (commands, screens, exact text)
expected:      what the participant expected and why
reproduce:     smallest steps from a clean install
evidence:      screenshot or log reference (consented), no credentials, no licensed data
participant:   pseudonymous id, role, experience band
```

## Consent and recording

Read and record verbal consent before recording:

> This session will be recorded (screen and audio) so we can improve the tool. The recording is stored
> locally, used only for this evaluation, and deleted on request. Your name will not appear in any
> published result; you will be identified by a pseudonymous id. You may stop the recording or the
> session at any time.

Do not record credentials, personal data or third-party licensed material. If such material appears,
stop the recording and delete that segment.

## Raw results

One JSON document per participant conforming to
[beta_eval_results.schema.json](beta_eval_results.schema.json). Aggregate only after all sessions are
recorded, and keep per-participant files so a claim can be traced to a session. Never fabricate or
reconstruct a session that did not happen; an empty results array with `status: "not_run"` is the
correct record for this release.
