# Phase 9.6.2 — Advanced workstation recovery

## Instrument binding

Root cause of the 9.6.1 failure was the browser check, not the save path: the test reopened
`items[items.length - 1]` from `/api/workspaces`, which is not the desk it had just saved, so it
restored an older desk with no binding. The save path itself writes `issuer_id`/`security_id` and
`link_group`, the validator whitelist accepts them, and storage round-trips them.

Fix: the check selects the saved desk by name (unique per run) and asserts the restored instrument
equals the value selected before saving. Result: `ISS-CIK0000718877` before and after reload.
Link-group membership, active group, availability mode and cutoff are part of the serialized link
state and survive the same round trip.

## Single-panel layout

Root cause: `defaultWorkstationLayout(['a'])` returned a split with one child. Both validators
reject that (`A split needs 2 to 6 children`). A lone panel is now a tabs node.

Frontend tests added: six panels to one, one to two, split collapse, closing the active tab,
reloading a one-panel desk, and five repeated add/remove cycles. Backend validation of the saved
document is exercised by the browser journey, which now saves and reopens a one-panel desk.

## Evidence

Browser run: 23/23 checks, 0 console errors, 0 failed requests, screenshots
`artifacts/phase9_6_2_advanced_filing.png` (visually inspected) and `..._mobile.png` (captured; overflow verified programmatically, not visually inspected).
