# ADR 0012 — React + Vite + lightweight-charts for the terminal UI

- **Status**: accepted (Phase 2)
- **Date**: 2026-11-04

## Context

The terminal needs dense financial tables, interactive charts, an inspector panel, a
screener form and a panel-based workspace editor. It must run locally on modest hardware,
be readable by one developer, and not become a second source of truth for numbers.

## Decision

* **React 19 + TypeScript + Vite 7.** Vite's dev proxy (`/api` → `127.0.0.1:8000`) keeps
  the client same-origin in development; production is a static `dist/` served by the
  same FastAPI process, so there is no CORS surface in normal use.
* **`lightweight-charts` 5.2.1** for price, index and indicator panes. It renders canvas
  charts with built-in crosshair, time scale and markers, which would be days of work to
  reproduce and is exactly the licence-free dependency the project allows. No chart data
  is generated in the browser: the API returns the bars, index points and indicator series.
* **No component/grid library.** Tables are small (tens of rows), so a custom
  `StatementTable` with sticky first column and a custom workspace CSS grid are simpler
  than adopting a data grid, and keep keyboard/ARIA behaviour under our control.
* **Typed API client, one file.** `web/src/api.ts` mirrors the JSON contracts in
  `web/src/types.ts`; every request goes through one `request()` helper that turns the
  server's error envelope into a typed `ApiError`. There are no `fetch` calls scattered
  through components.
* **One backend for both modes.** Standard and Advanced render the same responses; the
  mode only gates UI affordances (workspace editor, raw as-of controls, indicator
  parameters). Switching modes re-renders, it does not refetch different maths. The e2e
  suite compares statement text across a mode switch.
* **Server state is fetched with a small hook**, not a cache library. `useAsync` keys on
  an explicit dependency list; aborted/stale responses are ignored. Preferences
  (theme/mode) are persisted through `/api/settings`, with local state as the fallback.
* **Design system in CSS variables** (`styles.css`) with a dark default, a light theme,
  and breakpoints at 1100px and 760px. Dense tables scroll horizontally inside their card
  rather than forcing page overflow.
* **Vitest + Testing Library (jsdom)** for formatting/unit tests; **Playwright** for the
  browser journeys and screenshots.

## Consequences

* Production bundle is ~525 kB (164 kB gzipped), dominated by React and the chart library.
  Vite warns about the chunk size; code-splitting the chart is a possible later change,
  not a correctness issue for a local app.
* The workspace grid is CSS-grid based, so spans are integers with no drag-to-resize
  handles; resize/rearrange is explicit (buttons), which is also easier to test and to
  validate server-side.
* No global state library: page state is local, server data is per-page. That is enough
  for this screen set but would need revisiting for cross-page comparisons.
* Accessibility is deliberate but not audited: real `<table>` semantics, labelled inputs,
  `role="tablist"`, visible focus. A screen-reader audit is outstanding.
* Playwright's Chromium needs shared libraries that this container does not ship. The
  verification script documents a workspace-local sysroot fetched by
  `scripts/fetch_browser_libs.py`; that is a test-environment concern, not a product one.
