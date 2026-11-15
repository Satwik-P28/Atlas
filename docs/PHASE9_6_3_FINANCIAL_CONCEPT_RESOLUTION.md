# Phase 9.6.3 — Financial concept resolution

Module: `src/atlas/research/financial_concepts.py` (resolver version 9.6.3).

## Pipeline

Research requirement → concept (`CONCEPTS`, 11 bounded concepts with XBRL tag names) → candidate
rows → statement/scope filters → period → unit → verified cell.

## What counts as evidence

* Aliases are **candidates**, never proof. Exact label match scores 3.0; a phrase match 2.x; a
  token-subset match 1.0 and is now **rejected** (`weak_alias_match`).
* Qualified rows are penalised: "Less: …", "noncontrolling", "before income taxes", "per share"
  cannot satisfy a concept. This removed a false assertion where Coca-Cola's noncontrolling-interest
  line was answered as net income.
* Segment/parent-company presentations are penalised and excluded when a consolidated presentation
  exists.
* Companion rows validate statement identity inside one table: total assets requires liabilities
  and equity; revenue requires cost of sales/gross profit/operating income; net income requires
  operating income or share counts.

## XBRL

No XBRL fact table exists in this corpus. The resolver reports
`xbrl_status = unavailable: no XBRL fact table in this corpus`; concept identity is lexical plus
structural, and the artifact says so.

## Vintage policy

The filing whose own period is the requested year is preferred. If any other available filing
reports a different value for the same concept and period, Atlas returns `vintage_conflict` with
both vintages rather than choosing one.

## Result on the corpus

On the 6 numeric-direct questions with a detected concept, 2 resolved and 1 carried the reference
value. Several abstentions are correct (JPMorgan has no gross profit; 3M has both consolidated and
segment "Net sales"). Others expose gaps: Coca-Cola's 2022 column has no period; JPMorgan's
consolidated and parent-company tables both survive companion filtering.
