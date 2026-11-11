# Phase 9.4 — professional financial terminal interface research

Scope: a documentation-level study of professional research terminals, used to decide what
Atlas should adopt. No licensed product was accessed, no proprietary graphic, layout or asset
was reproduced, and no screenshot of a commercial terminal was used as a visual reference.
Everything below is an interaction pattern read from public documentation, help centres and
product pages, with the workflow problem it solves and whether Atlas already has the backend
capability to support it.

## 1. Comparison matrix

| Product | Interface pattern | User benefit | Atlas adaptation | Priority | Implementation feasibility |
| --- | --- | --- | --- | --- | --- |
| Bloomberg Terminal / Launchpad | Linked windows following one security | One selection drives chart, statements and news; no retyping | Link groups A–D; panels declare which parameters they accept | P0 | Shipped: reducer + 8 panels |
| Bloomberg Terminal | Function codes (`DES`, `FA`) and a command line | Keyboard reaches any function without menus | Command grammar (`AAPL FIN`, `SET ASOF …`) with registry, aliases and completion | P0 | Shipped, parser unit-tested |
| Bloomberg Launchpad | Multi-panel workspace saved and restored | A desk survives a restart | `atlas.workspace.v2` document: split/tab layout, validated server-side, saved through the existing workspace API | P0 | Shipped |
| LSEG Workspace | Cross-asset, multi-application navigation | Analysts move between instrument, research and portfolio without losing context | Rail navigation + palette; one route per capability; instrument context lives in the shell | P0 | Shipped |
| FactSet | Company dashboard with statements, estimates and source inspection | Dense fundamentals with provenance one click away | Statements panel where every cell opens the evidence inspector | P1 | Shipped (statements + X-Ray) |
| FactSet / Koyfin | Tabular financial statements with fixed labels and scrollable periods | Comparability across periods without losing the line item | Existing statement table plus frozen label column and tabular numerals | P1 | Existing, restyled |
| Koyfin | Command bar search (`SPY`, `AAPL`, `NVDA`) | Fast symbol entry without pointer travel | Palette resolves tickers, CIKs and name prefixes; refuses unknown symbols | P0 | Shipped |
| Koyfin | Resizable, saved dashboard widgets | Users tune density to their screen | Split/tab docking with pointer and keyboard resizing, persisted | P1 | Shipped (custom engine) |
| OpenBB Workspace | Composable widgets with shared parameters | Reusable analytical building blocks | Typed panel registry; panels receive link context instead of prop drilling | P1 | Shipped |
| QuantConnect / LEAN | Backtest result inspection with statistics and equity curve | Trust in a quantitative result | Not implemented in this phase: Atlas shows registered model/indicator versions and validation output, not a new backtest UI | P2 | Deferred, needs a validated run contract |
| JupyterLab / VS Code workbench | Tabs and splits over one workspace | Several analyses side by side | Tab groups inside split panes, maximize/restore | P0 | Shipped |
| VS Code | Command palette with fuzzy-ish prefix matching | Discoverability for keyboard users | Palette with kinds, descriptions, arrow navigation and error candidates | P0 | Shipped |
| TradingView | Crosshair, legend and range presets on a price chart | Read a series precisely | Existing Lightweight Charts integration reused unchanged | P2 | Existing |
| Professional database IDEs | Read-only diagnostics and provenance panes | Explain why a number looks odd | Diagnostics panel + evidence inspector | P1 | Shipped |
| AG Grid-style dense tables | Sticky headers, right-aligned numbers, tabular numerals | Scan large tables quickly | Table primitives in `design/advanced.css`; virtualization not added | P2 | Partial: no virtualisation yet |
| Aladdin / Portfolio Visualizer | Risk decomposition, factor exposure | Portfolio-level questions | Not addressed: Atlas has institutional lab analytics but no factor model contract to expose honestly | P3 | Deferred |

Patterns identified: 14. Implemented in this phase: 11. Deferred: 3, each because the backend
contract does not exist yet and inventing one would violate the project's evidence rules.

## 2. What was deliberately not copied

- No Bloomberg-style coloured function keys, no invented tickers, no fake "real-time" tape.
  Atlas's market data is explicitly stamped `synthetic` / `imported` / `no_data`.
- No "terminal" monospace-everywhere aesthetic. Monospace is reserved for numbers, ids,
  timestamps and commands; labels stay in the sans stack so prose remains readable.
- No dense grid of decorative KPI tiles. The workstation gives that space to real panels.

## 3. Docking engine choice

Candidate: `flexlayout-react` — MIT, version 0.11.1 published 2026-09-26, peer dependencies
`react ^18.0.0 || ^19.0.0`, so it is React 19 compatible and actively maintained.

Selected instead: a small in-repository layout engine (`web/src/terminal/docking/layout.ts`,
~380 lines) with an explicit split/tab grammar. Reasons, in order:

1. **The saved layout must be validated by the server.** `atlas.workspace.v2` refuses unknown
   node types, unknown keys, weights that do not sum to one, panels placed twice and orphaned
   panels. Persisting a third-party model's JSON would either bypass that validation or require
   translating an untyped structure into our grammar anyway.
2. **No browser was available to verify a heavy third-party widget** (see the browser
   acceptance report). A dependency whose drag-and-drop, measurement and persistence behaviour
   cannot be exercised here is a liability; a pure reducer can be, and is, unit-tested.
3. **Scope.** The workstation needs tabs, splits, resize, move-to-dock, maximize, save, restore
   and reset. Those are ~15 pure functions and ~200 lines of rendering, which is less surface
   than configuring and constraining flexlayout for the same validated persistence.

The trade-off is explicit: detached browser windows and multi-monitor docking are **not**
implemented. If those become requirements, `flexlayout-react` remains the right upgrade path,
and the v2 grammar can be converted to its model deterministically.

## 4. Sources

- https://www.bloomberg.com/professional/
- https://www.lseg.com/en/data-analytics/products/workspace
- https://www.factset.com/
- https://www.koyfin.com/help/mydashboards-myd/
- https://www.koyfin.com/help/command-bar-search/
- https://docs.openbb.co/workspace
- https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results
- https://github.com/caplin/FlexLayout (evaluated, not adopted; see §3)
- npm registry metadata for `flexlayout-react` (version, licence, peer dependencies)
