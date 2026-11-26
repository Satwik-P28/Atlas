# Phase 9.4 — design system

Implemented in `web/src/design/tokens.css` (tokens) and `web/src/design/advanced.css`
(workstation composition). Two systems share one vocabulary; components never hard-code a
colour, so Standard and Advanced stay legible under either theme.

## 1. Surfaces and borders

| Token | Advanced (dark) | Standard light | Standard dark |
| --- | --- | --- | --- |
| `--bg` app background | `#080b0f` | `#f7f8fa` | `#0b0f14` |
| `--bg-elevated` chrome | `#10151b` | `#ffffff` | `#0f151c` |
| `--bg-input` fields | `#0b1015` | `#ffffff` | `#0c1219` |
| `--bg-raised` hover | `#161d25` | `#f1f3f6` | `#0d141b` |
| `--border` | `#27313c` | `#dde3ea` | `#1e2a36` |
| `--border-strong` | `#35424f` | `#c3ccd6` | `#2b3a48` |

Radii are 3–6 px, 10 px only for the command overlay. Panels are bordered, not shadowed: an
18-panel desk with drop shadows is visual noise, and Advanced sets `--shadow-panel: none`.

## 2. Typography

- Sans (`Inter` → system stack) for labels, prose and navigation.
- Mono (`ui-monospace` → SF Mono/JetBrains/Consolas) for numbers, ids, timestamps, commands,
  logs and provenance. `font-variant-numeric: tabular-nums` and `"tnum"` are applied through
  `.mono`, `.num` and `.fin-num`.
- Scale: 10/11/12/13/14/16/20/26 px. Advanced body is 12.5 px; Standard body is 13 px.
  Nothing is scaled below 10 px, and no control shrinks below a 26 px Advanced / 30 px
  Standard hit height.
- Text is never letter-spaced for numbers; upper-case micro-labels use 0.08–0.12 em tracking.

## 3. Density

| Token | Standard | Advanced |
| --- | --- | --- |
| `--density-row` | 30 px | 26 px |
| `--density-control` | 30 px | 26 px |
| `--density-pad` | 10 px | 8 px |

Density is a token, not a global `font-size` trick: the two systems differ in spacing and
chrome weight, and both stay above the legibility floor.

## 4. Semantic colour and measured contrast

Contrast was measured with the WCAG 2.x relative-luminance formula rather than eyeballed:

| Pair | Ratio |
| --- | --- |
| Advanced text on app background `#e7edf4` / `#080b0f` | 16.73 : 1 |
| Advanced text on panel `#e7edf4` / `#10151b` | 15.56 : 1 |
| Advanced secondary `#98a6b5` / `#10151b` | 7.39 : 1 |
| Advanced faint `#71808f` / `#10151b` | 4.53 : 1 |
| Advanced accent `#4fb3d9` / `#10151b` | 7.67 : 1 |
| Advanced positive `#46b17b` / `#10151b` | 6.84 : 1 |
| Advanced negative `#d96459` / `#10151b` | 5.17 : 1 |
| Advanced synthetic violet `#9d7bea` / `#10151b` | 5.64 : 1 |
| Advanced warning `#d9a441` / `#10151b` | 8.15 : 1 |
| Standard light text `#0f1720` / `#f7f8fa` | 16.98 : 1 |
| Standard light muted `#55636f` / `#f7f8fa` | 5.81 : 1 |
| Standard light accent `#0b62c4` / `#f7f8fa` | 5.55 : 1 |
| Standard dark text `#e6edf3` / `#0b0f14` | 16.27 : 1 |
| Standard dark muted `#93a1ae` / `#0b0f14` | 7.28 : 1 |

Every pair meets WCAG AA for normal text (4.5:1); the lowest is Advanced faint at 4.53:1, used
only for tertiary metadata. Synthetic data keeps its own violet so it can never be mistaken for
observed or reported data, which use accent and neutral respectively.

## 5. Interaction

- Focus is always visible: `:focus-visible` gets a two-ring `box-shadow` built from the surface
  and accent tokens, so it works on both systems without a colour that disappears on light.
- Hover states change one surface step, never colour alone; `prefers-reduced-motion` removes
  transitions.
- Tabs are a real `tablist` with `aria-selected`, arrow-key roving and per-tab close buttons.
  Splitters are `role="separator"` with arrow-key resizing (Shift for a coarse step).
- Numbers carry their unit or are formatted through `format.ts`, which never rescales a value:
  `fraction` renders as a percentage, `ratio` as a multiple, `missing` as `—`.

## 6. Primitives

`.wb-group` / `.wb-tabs` / `.wb-body` (panel chrome), `.tp-table` (dense financial table),
`.tp-kv` (provenance key/value), `.tp-badge` (data status), `.tp-empty` (honest empty state),
`.tp-error` (failure), `.ws-banner` (desk-level notice), `.palette*` (command overlay),
`.adv-fact` (header status), `.insp-*` (inspector). Component-level React primitives are the
existing `Badge`, `Loading`, `ErrorState`, `EmptyState` and `SectionHeader`, reused rather than
duplicated.

Deliberately absent: decorative gradients, KPI-tile grids, coloured badges for their own sake,
and any chart element that does not correspond to a series the API actually returned.
