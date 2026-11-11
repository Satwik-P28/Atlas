# Phase 9.4 — frontend architecture

## 1. Shape

```
web/src/
  App.tsx                     one router, two shells
  shell/
    StandardShell.tsx         top navigation research desk
    AdvancedShell.tsx         command header, rail, desk, inspector, status bar
  terminal/
    links.ts                  link-group state + pure reducer
    linkContext.tsx           provider and hook
    command/
      registry.ts             typed command grammar, aliases, completions
      CommandPalette.tsx      keyboard overlay
    docking/
      layout.ts               split/tab grammar + pure desk operations
      Workbench.tsx           renderer: tabs, splitters, drag-to-dock, maximize
    panels/
      registry.tsx            typed panel registry and the eight panels
  design/
    tokens.css                surfaces, typography, spacing, density, focus
    advanced.css              workstation chrome, workbench, palette, tables
  pages/Workstation.tsx       desk page: layout state, save/restore, commands
  components/SecuritySearch.tsx   shared instrument search
```

Standard pages (Markets, Company, EquityResearch, Lab, …) are unchanged in behaviour: they
render inside whichever shell is active, and they read the same API modules and formatting
helpers. No page keeps a second copy of a financial formula.

## 2. Why the mode lives in the shell

`App.tsx` chooses a shell from the persisted `mode` setting. Standard and Advanced therefore
share the router, the data layer and the evidence contracts, and a mode switch cannot change
a number — it remounts presentation. Desktop state (dock layout) lives in a workspace document,
not in a shell-level store, so switching modes never leaves a half-applied layout behind.

## 3. Docking model (`atlas.workspace.v2`)

```jsonc
{ "type": "split", "direction": "row", "weights": [0.6, 0.4], "children": [
  { "type": "tabs", "active": "statements", "panels": ["statements", "metrics"] },
  { "type": "tabs", "active": "evidence",  "panels": ["evidence"] }
]}
```

Invariants enforced by **both** `src/atlas/terminal/workspaces.py` and
`web/src/terminal/docking/layout.ts`:

- node types are `split` and `tabs`, no others;
- splits have 2–6 children, weights of 0.05–0.95 summing to 1 (±1e-6), normalised to 6 dp;
- tab groups hold 1–8 panels, `active` must be a member, no repeated panel anywhere;
- every panel in the document appears exactly once in the layout;
- nesting depth ≤ 5, total nodes ≤ 40;
- unknown keys are refused, so a document cannot smuggle executable configuration.

`atlas.workspace.v1` documents still validate and remain loadable: a v1 grid is converted to a
v2 layout deterministically from its columns and spans. Presets stay v1, which the existing
tests pin.

Unit tests: `web/src/terminal/docking/layout.test.ts` (18 cases) and
`tests/test_phase9_4_workspace_layout.py` (13 cases) exercise the same grammar from both sides.

## 4. Link groups

`LinkState` holds four group selections plus a desk-wide information cutoff and availability
mode. Panels declare what they accept (`instrument`, `security`, `cutoff`, `mode`); ungrouped
panels follow the active group. The cutoff is deliberately **not** per-panel: it decides which
evidence is allowed to exist, so no panel may opt out of point-in-time truth. The inspector
states the active policy, and every panel that cannot render says which input is missing.

## 5. Commands

`parseCommand` returns a typed `AtlasCommand` or a structured error (`unknown_instrument`,
`ambiguous_instrument`, `unknown_topic`, `invalid_date`, `invalid_mode`, `unknown_workspace`,
`empty`). It never resolves a symbol to a demo page, never runs a shell, and offers candidates
on failure. `completeCommands` powers the palette and preserves a trailing space so `AAPL `
means "topics for AAPL".

## 6. Persistence and failure behaviour

- Save validates the layout locally, then posts a v2 document to the existing workspace API,
  which validates it again and returns a fingerprint.
- Open validates the stored layout; if the server accepted it but the client cannot parse it
  (older or corrupt document), Atlas derives an arrangement from the panel list and says so in
  a warning banner instead of rendering nothing.
- A panel that throws is contained by its own panel boundary state; a failed request shows the
  error with a retry, never fabricated data.
- `Ctrl/Cmd+S` saves the desk through a window event, so the shortcut works from any focus.

## 7. Invariants preserved

1. Evidence ids stay attached to displayed values; the inspector resolves them.
2. Cutoff/mode are passed to every statement, metric and chart request.
3. Missing observations stay missing (`—`, never zero).
4. Contradictions are surfaced, not reconciled (statements panel reports their count).
5. Synthetic and imported data keep their badges.
6. Memo hashes are untouched by this phase; the memo panel only reads and re-checks saved
   versions.
7. Export rights are untouched; the memo panel exposes no export that bypasses them.
8. Unimplemented capability is labelled: backtest inspection and factor analytics are deferred,
   not faked.
