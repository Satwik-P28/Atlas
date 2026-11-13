# Phase 9.6.2 — Clean release candidate

`d8ae4f1` on the development branch contains licensed FinanceBench question text from Phase 9.6.
Later commits sanitized the working artifact but cannot remove that content from history.

## Non-destructive candidate

A branch is created directly from `main` (`486e7d0`) whose tree equals the reviewed development
tree, using a new commit whose only parent is `main`. No commit in its ancestry is `d8ae4f1`, and
no prohibited text is reintroduced. The candidate is pushed separately and inspected
independently: ancestry (`git merge-base --is-ancestor d8ae4f1 candidate` fails), tree equality
against the development tip for implementation files, presence of schema 15 migrations, and the
sanitized evaluation artifacts.

## What this does not fix

The problematic commit remains in the development branch, in GitHub's retention and in any clone
already fetched. A clean candidate prevents it from entering `main`; it does not remove it.
Removing it requires an owner-authorized history rewrite or an explicit private-retention decision.

## Rights assessment

FinanceBench open material is distributed under CC BY-NC 4.0; the corpus is kept private, the
evaluation artifact contains counts and metrics only, and no licensed question or answer text is
committed. The presence of CC BY-NC material in a private repository is not by itself a licence
violation, and this phase does not assert one. It also does not claim history is clean: retention
of `d8ae4f1` is an open item for the repository owner. `main` is not promoted.
