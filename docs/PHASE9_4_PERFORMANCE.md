# Phase 9.4 — performance

Everything here was measured in this environment. There are no browser runtime measurements,
because no browser could start (see the browser acceptance report), and no speedup is claimed.

## 1. Production build

`npm run build` (`tsc -b && vite build`):

| Measurement | Result |
| --- | --- |
| Build duration | 2.89 s |
| JavaScript bundle | 767.15 kB (225.52 kB gzip) |
| CSS bundle | 57.46 kB (11.10 kB gzip) |
| Typecheck | passes (project references, `--noEmit`) |

Vite warns that a chunk exceeds 500 kB. That is a real regression risk, not a cosmetic warning:
the new shells, eight panels and the docking renderer all land in one chunk. Code splitting was
**not** implemented in this phase. The next step is route-level `React.lazy` for the labs and
studio pages plus a manual vendor chunk, measured against this 767 kB baseline.

## 2. Test and analysis cost

| Check | Result |
| --- | --- |
| Vitest (layout, command, links, formatting) | 45 tests, 4 files, ≈4 s |
| TypeScript typecheck | passes |
| Backend suite (full) | passes, no failures or errors |
| New backend layout tests | 13 cases (`tests/test_phase9_4_workspace_layout.py`) |
| Master specification integrity | verified, size and SHA-256 unchanged |

## 3. What was not measured

- Initial render, time to interactive, first paint.
- Workspace and instrument switching latency.
- Table interaction, panel drag and resize frame cost.
- Chart update cost, memo rendering, large claim-register rendering.
- Browser memory consumption.

These require a browser. The committed Playwright journey is the vehicle for them; until it runs,
any statement about frontend responsiveness would be invented.

## 4. Backend impact

This phase added three panel types (`memo`, `model`, `diagnostics`) and the v2 layout validator.
It did **not** touch the memo build, save, reopen, export or change-detection paths, so the Phase
9.3 measurements remain the reference: memo build 4.0 s (JPM) / 4.5 s (AAPL) median, save 15–21 ms,
reopen 2–3 ms, change check 3–4 ms, exports 3–13 ms. Those numbers were not re-run here because
nothing in that path changed; re-running them would not be a comparison.
