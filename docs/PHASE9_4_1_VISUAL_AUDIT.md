# Phase 9.4.1 — visual and interaction audit

Screenshots inspected directly (not inferred from code): 1440×900 Advanced desk with live data
(`artifacts/phase9_4_advanced_desk.png`), the 1440×900 Standard desk, and the 390×844 phone
layout. Every screenshot referenced here was produced by the committed journey against
`var/phase9_export.db`.

## 1. Defects found and fixed in this phase

| # | Defect | Evidence | Fix |
| --- | --- | --- | --- |
| 1 | Header and status bar asserted **"database unavailable · offline · 0 evidence"** before the first health response arrived | Advanced desk screenshot taken during the load | Three states now (`checking…` / `online` / `offline`); counts render only when known |
| 2 | Memos table wrapped object ids into five lines and clipped the **Check** button | Advanced desk screenshot | `.tp-clip` truncation with full value on hover; buttons never wrap |
| 3 | Statement and metric figures were **clipped mid-number** in narrow panels ("$40…") | Advanced desk screenshot | Tables size to content and scroll horizontally inside the panel; digits are never truncated |
| 4 | Panel title squeezed by a long meta line ("ALPHABET INC." wrapped while metadata ran across) | Advanced desk screenshot | Title ellipsises, meta capped at 58 % and right-aligned |
| 5 | Saving a desk whose name was taken failed with **409 and left the desk unsaved** | Journey save step | Name chosen from the live workspace list before create; 409 suffix retry kept as a backstop |
| 6 | 390 px header collisions: command trigger, mode switch and theme button overlapped | `phase9_4_standard_mobile.png` | Header wraps, secondary path/⌘K hidden, brand subtitle dropped, trigger ellipsises |
| 7 | A desk containing an unpinned evidence inspector could not be saved (**422**) | Journey save step | New `evidence` panel type that needs no pinned observation; `xray` still requires one |
| 8 | Journey assumed Standard mode, but mode is persisted server-side | Second run opened in Advanced | Journey selects its mode explicitly and restores Standard afterwards |

Items 1, 2, 3, 4, 6 are visual defects found by looking at the rendered pixels. Items 5 and 7 are
functional defects the browser exposed; neither would have been visible from a typecheck.

## 2. Assessment against the design standard

**Information density.** The 1440×900 desk fits six live panels — universe, chart, statements,
metrics, evidence, memos — with no wasted bands. Statements show five annual periods, metrics
twenty-four rows, memos eighteen versions. Chrome is 28 px per tab strip and a 22 px status bar.

**Typography and numbers.** Numbers are monospaced and tabular; labels stay sans. Statement
amounts and metric values right-align on a consistent digit column, and missing values render as
`—`, never `0`.

**Restraint.** No gradients, no card shadows on the desk, one accent used for selection and
focus. Colour carries meaning: synthetic violet, positive green, negative red, warning amber.

**Disclosure.** Panels that cannot render say why ("No bars for this security at this cutoff",
"No instrument selected in this link group", "No priced securities in this database"). The status
bar names the cutoff and link group at all times.

**Mobile.** At 390×844 the rail becomes a horizontal strip and the desk stacks; panels remain
scrollable and operative. The inspector is desktop-only and is hidden rather than squeezed. This
is a compact adaptation, not a phone-native workstation, and the interface does not pretend
otherwise.

## 3. Remaining observations (not release-blocking)

- The memos version column still wraps a long semantic version across two lines at 1440 px.
- With no price bars the universe panel reads "0 securities" while the inspector can still select
  an issuer; both statements are true but the combination reads oddly.
- The Advanced rail labels truncate to four characters ("Rsrch", "Quant"); they are tooltipped.
- Statements at 1440 px in a four-column desk need horizontal scrolling; the figures are correct,
  but a user may prefer a three-panel desk for that task.
- **390 px header (verified after the fix):** the command trigger and mode switch no longer collide,
  but the theme button is still partly clipped at the right edge. Cosmetic, not blocking; the desk
  and navigation remain fully operable.
- **390 px capture conditions:** `phase9_4_standard_mobile.png` was taken while the companies list
  was still loading and with the Advanced rail active, so it evidences the phone layout and chrome,
  not loaded data. The 390 px Standard list check therefore passes on a page in its loading state
  and is weaker evidence than the desktop equivalent.
- No screen-reader or forced-colours verification was performed.

## 4. How to re-run the visual review

```bash
cd web && ATLAS_ARTIFACTS=../artifacts node e2e/phase9_4_workstation.mjs
```
Screenshots are written to `artifacts/phase9_4_*.png`; the journey fails on console errors or
failed requests, so a clean run also means the captured pixels came from an error-free page.
