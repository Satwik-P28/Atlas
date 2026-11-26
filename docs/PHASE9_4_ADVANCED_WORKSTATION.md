# Phase 9.4 — Advanced workstation (Atlas Quant)

Advanced is a different application, not Standard with more buttons: a command header, an icon
rail, a dockable desk, a context inspector and a status bar that states the cutoff and the data
condition. It is dark-first and keyboard-driven.

## 1. Composition

`web/src/shell/AdvancedShell.tsx` renders a five-region grid:

```
┌──────────────────────────────────────────────────────────────┐
│ ATLAS  ⌘K command · instrument · desk | cutoff | mode | data │  header
├────┬─────────────────────────────────────────┬───────────────┤
│rail│ dockable workbench (splits + tab groups)│   inspector   │
├────┴─────────────────────────────────────────┴───────────────┤
│ evidence online · bars · link group · cutoff · mode          │  status
└──────────────────────────────────────────────────────────────┘
```

At 1920×1080 the default desk shows six live panels. At ≤1180 px the inspector collapses to a
toggle; at ≤900 px the rail becomes a horizontal strip, the inspector hides, and horizontal
splits stack vertically with a 240 px minimum pane height. Advanced is usable on a phone but
does not pretend to be a desktop desk there: the inspector and multi-pane docking are
desktop affordances.

## 2. Desk operations

Implemented in `web/src/terminal/docking/layout.ts` (pure) and `Workbench.tsx` (render):

| Operation | How |
| --- | --- |
| Add panel | Toolbar picker, or a command (`AAPL FIN`) |
| Close panel | Tab `×`; the split collapses when a group empties |
| Resize | Drag the splitter, or focus it and use ←/→/↑/↓ (Shift = coarse) |
| Reorder / tab | Drag a tab onto another tab strip |
| Dock to a side | Drag a tab onto the left/right/top/bottom edge of a panel body |
| Maximize / restore | `⤢` on the tab group |
| Save | Toolbar, `⌘S`, or `SAVE WORKSPACE` |
| Reopen | Rail → Saved, or `WORKSPACE <name>` |
| Reset | Toolbar, or `RESET LAYOUT` |
| Recover | An unparseable saved layout is replaced by a derived arrangement plus a warning |

Weight changes are normalised to 6 dp and clamped so a pane can never vanish; a splitter drag
returns a new tree, so nothing is mutated in place.

## 3. Panels

`web/src/terminal/panels/registry.tsx` defines a typed registry. Each panel declares which link
parameters it accepts, and each renders only data the API returned:

1. **Universe monitor** — covered securities, latest close, 1D/1Y change, sessions, data status,
   sortable columns; selecting a row sets the link group's instrument.
2. **Price chart** — range presets, adjustment policy and coverage line, Lightweight Charts.
3. **Financial statements** — point-in-time income/balance/cashflow, annual or quarterly; every
   cell with evidence opens the inspector; contradiction count is surfaced.
4. **Valuation metrics** — value, formula and supporting evidence ids per metric; missing metrics
   are listed, not zeroed.
5. **Evidence inspector** — value, period, availability precision, quality, source, licence,
   derivation, filing, revision chain length, limitations.
6. **Research memo** — saved versions with content hash and saved date, plus a change check that
   renders the response's own fields.
7. **Model registry** — the service contract's schema keys and the registered indicator versions
   read from `/api/schema` and `/api/indicators`.
8. **Diagnostics** — `/api/health` fields, desk cutoff/mode and workspace schema.

Nothing is simulated: there is no backtest panel, no order ticket, no fabricated quote, and no
"AI" chat surface. Deferred capabilities are named in the final report rather than faked.

## 4. Command grammar

`⌘K` / `/` opens the palette. `⌘⇧P` opens it too. `⌘S` saves.

```
AAPL                 select instrument
JPM FIN              select JPM, open statements
AAPL EVIDENCE        open the evidence panel
SET ASOF 2024-06-01  move the information cutoff
SET MODE public_available | atlas_ingested
WORKSPACE Desk A     open a saved layout
SHOW DIAGNOSTICS     open diagnostics
SAVE WORKSPACE  ·  RESET LAYOUT  ·  HELP
```

Errors are typed and shown in the palette: `unknown_instrument` (with candidates),
`ambiguous_instrument`, `unknown_topic`, `invalid_date`, `invalid_mode`, `unknown_workspace`.
Commands route to real actions; none of them executes a shell.

## 5. Link groups and point in time

Groups A–D each hold an issuer and a security. A panel joins one group (the tab shows a coloured
dot) or none, in which case it follows the active group. The information cutoff and availability
mode are desk-wide, because they decide which evidence may exist; the inspector always states
which policy is active, and a panel with no instrument says so instead of rendering empty
numbers.

## 6. Persistence

The desk is saved as `atlas.workspace.v2` through the existing workspace API. The document holds
the panel list, each panel's link group, and the split/tab layout. The server validates the same
grammar, returns a fingerprint, and refuses unknown panel types or config. Loading validates
again on the client; a rejected layout degrades to a derived arrangement with a visible warning
rather than a blank desk.

## 7. What this phase could not verify

Docking, resizing, drag-to-reorder and the 390×844 layout were implemented and unit-tested at the
model level, but **not exercised in a browser** here (Chromium cannot start in this environment).
The committed journey `web/e2e/phase9_4_workstation.mjs` drives all of it and captures screenshots
and console/network errors when run where a browser works.
