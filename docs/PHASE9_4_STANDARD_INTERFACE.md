# Phase 9.4 — Standard interface (Atlas Research)

Standard is the research desk: a top navigation bar, one guided workflow per page, comfortable
density and the evidence caveats kept in the open.

## 1. Structure

`web/src/shell/StandardShell.tsx`

```
ATLAS  research terminal
Markets · Securities · Research · Memos · Screeners · Models · Portfolios · Workspaces · Quant lab · Watchlists
                                        evidence count · search · Standard/Advanced · theme
```

- **Top navigation** replaces the previous sidebar. Ten sections, horizontally scrollable on
  narrow screens, active section marked with an accent underline rather than a filled pill.
- **Utilities**: the live evidence count with an online/unavailable dot, shared instrument
  search, the mode switch and the theme toggle.
- **Content** keeps every existing page: markets overview, company research, equity memos,
  screeners, model studio, quant lab, institutional lab, learning and economic labs,
  applications, watchlists and saved workspaces.
- **Footer** states the data position: public-domain filings, no bundled prices, exports honour
  source rights, with a link to the point-in-time policy.

## 2. What changed and what did not

Changed: the shell, typography and density tokens, search (now a shared component used by both
shells), and the removal of the persistent sidebar. Not changed: every page's data flow, every
financial calculation, every evidence link, the memo save/review contract and the server API.

That is deliberate: this phase is a presentation overhaul, and a presentation overhaul must not
move a number. The company page still renders point-in-time statements, the metric grid still
shows formulas and evidence ids, and the memo panel still refuses to save a memo the analyst did
not review.

## 3. Research usability details

- Tables keep a frozen label column and scroll periods horizontally; numbers are right-aligned,
  tabular and unit-labelled by `format.ts`.
- Empty and error states name the reason ("No amounts in this view", "No database yet") instead
  of showing a blank panel.
- Search refuses to resolve unknown text: "No instrument matches … Atlas does not invent one."
- Charts keep their adjustment policy, coverage and source notes visible under the series.

## 4. Mobile

At 390×844 the header wraps to two rows, the navigation becomes a horizontally scrollable strip
and utilities shrink. This composition was built against the existing responsive rules in
`styles.css` plus the new `.std-*` rules; it has **not** been visually verified in a browser in
this environment (see the browser acceptance report). The committed journey
`web/e2e/phase9_4_workstation.mjs` includes a 390×844 standard-mode overflow assertion that a
browser-capable environment can execute.
