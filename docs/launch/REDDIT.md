# Reddit drafts

## r/SecurityAnalysis

**Title:** I built a research tool that refuses instead of guessing — here is what it does on a real 10-K

**Body:**

Most tools answer a financial question with a number. I wanted one that answers with a *cell*: the
document, table, row and column, the raw text, the scale, and an independent recomputation — or a
refusal that names what was ambiguous.

Atlas is that tool. On Apple's FY2026 10-K it parses the filing into 60 tables and 728 text units,
answers "total net sales" as 478,834, and reproduces the same value and source-table hash on a fresh
installation. On a synthetic 10-K it runs a 30-step acceptance covering certificate, verification,
valuation, scenarios, comparison, memo and PDF.

Three things I deliberately did not do:

- No segment-total answers to consolidated questions. Refused, with candidates listed.
- No back-filling of history. Point-in-time cutoffs remove values that were not available; modelled
  availability bounds are labelled as modelled.
- No "the model is confident" claims. There is no generative model in the answer path.

It is local, single-user, unauthenticated, and an experimental preview. If you want to break it, the
most useful bug report is a filing where a citation looks right but is not.

## r/algotrading (data-wrangling angle)

**Title:** Parsing 10-K tables into citable cells: the `$`-column trap

**Body:**

Short version: when a filer puts currency symbols in their own table columns, a naive flatten puts
the first data column under the second header. The value is still recoverable; the *label* is not.
Atlas now reports `ambiguous_column_label` for those citations instead of asserting a year it cannot
vouch for, and its acceptance test recomputes an in-table identity (segment rows sum to the total)
rather than the gross-margin identity, which spans two tables and cannot be recomputed from one.

If you have dealt with this, I would like to compare approaches — the flattened header problem is
where most "the number is off by one column" bugs live.

## r/PersonalFinanceCanada / general (not recommended)

Skip it. Atlas is a research tool for people who read filings; posting it to consumer-finance
subreddits invites the exact misinterpretation the product refuses to make.
