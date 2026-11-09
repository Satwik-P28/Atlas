# Atlas external-beta user test plan

## Status: prepared, **not executed**

No external participant has run this. Nothing below is a usability, comprehension or trust
result. The previous protocol (`docs/USER_TESTING_PROTOCOL.md`) covered comprehension
questions; this one covers the full install-to-reproduction path.

## What the participant receives

- The repository at a stated commit.
- This document and `docs/PUBLIC_BETA_INSTALLATION.md`.
- A machine with Python 3.11+, Node 18+ and network access to install dependencies.
- No walkthrough from the implementer during the task.

## Walkthrough (the eleven required capabilities)

The commands assume a fresh checkout and a `.venv` in the repository root.

```bash
# 1. Clone
git clone https://github.com/Satwik-P28/Atlas.git && cd Atlas
git checkout <stated-commit>

# 2. Install
python3 -m venv .venv
.venv/bin/pip install -e .
npm --prefix web install && npm --prefix web run build

# 3. Initialise a clean database (committed fixtures only; no network)
.venv/bin/python scripts/build_phase9_db.py --db var/phase9.db

# 4. Start the terminal
.venv/bin/atlas --db var/phase9.db serve --port 8000
# open http://127.0.0.1:8000
```

Then, in the browser:

5. **Inspect an SEC-backed issuer.** Open JPMorgan Chase. Read the statements panel and
   confirm each value opens a provenance record naming the filing, accession and raw
   document hash.
6. **Run a supported model.** Open equity research for the issuer and run the bank
   residual-income model. Note the value, the calculated equity value and the audit.
7. **Change and compare assumptions.** Open the sensitivity grid and the scenario view;
   change cost of equity and ROE. Confirm the value changes and the comparison is shown
   against the base run.
8. **Inspect source provenance.** From any metric, follow the evidence id to the raw
   document summary (source, licence, retrieval time, SHA-256 prefix).
9. **Save and reopen.** Save the research object, reload the page, reopen it, and confirm
   the values and assumptions are identical.
10. **Export an application.** Download the `.atlas` package. Confirm the UI states it is
    unsigned and that its content hash is shown.
11. **Reproduce on a second installation.** On a second machine or a fresh database:

```bash
.venv/bin/atlas --db var/second.db init
.venv/bin/atlas --db var/second.db app install <downloaded>.atlas
.venv/bin/atlas --db var/second.db app execute <install_id> --json
```

   Compare `value_per_share`, `calculated_equity_value` and the package hash with step 10.

## Demo mode and synthetic data

`scripts/build_terminal_db.py --db var/atlas.db --force` builds a demonstration database
with four SEC issuers plus **synthetic** market series. Synthetic sources are labelled
`synthetic` in the source registry and the provenance panel says so; do not present them as
observed prices.

Market prices are absent from the committed fixtures. Anything price-dependent must say
"unavailable" rather than showing a number. If a participant sees a market-implied
valuation for JPMorgan, Goldman Sachs or UnitedHealth, that is a defect — those methods are
refused by policy (`docs/ICB_EXECUTION.md`).

## What participants must be told (limitations, verbatim)

- Atlas produces no rating, target price or recommendation.
- The DCF is a conditional model, not a forecast; the bank model is residual income with
  an average-common-ROE proxy, not a company-reported ROE.
- FR Y-9C evidence has no publication vintage; historical regulatory reconstruction is
  prohibited.
- Packages are unsigned: integrity is verified, publisher identity is not.
- The terminal is a local, single-user application with no authentication.

## Evaluation protocol

**Participants.** Minimum three, none of them the implementer; at least one with
professional financial-analysis experience and one without. Record role, prior tooling and
whether they have used Atlas before.

**Session.** 60–75 minutes, think-aloud, screen and audio recorded with consent. The
facilitator does not answer task questions during the attempt; each intervention is logged
as a failure with its cause.

**Measures per task.** Completed without help (yes/no), time on task, and the exact point
of failure. Aggregate: median time-to-first-valuation, setup time from clone to terminal,
number of setup errors, and count of limitation statements the participant can repeat
correctly afterwards.

**Misinterpretation probes.** After the tasks, ask: "Is this value a forecast?", "Is it a
target price?", "Does valid coverage mean the model is valid?", "Where did this number come
from?", "Could you publish this dataset?" A wrong answer is a finding even if every task
completed.

**Success criteria for beta readiness (proposed, not met yet).**

- 3/3 participants complete steps 1–9 unaided; 2/3 complete step 11.
- Median setup under 15 minutes on a warm network.
- No participant states the model is a forecast or a recommendation.
- Every participant locates provenance for one number.
- No task requires explaining internal architecture.

**Reporting.** Publish the participant count, every failed task verbatim, and the raw
timings. Do not convert a partial completion into a pass, and do not describe the beta as
validated until this protocol has actually been run with independent participants.
