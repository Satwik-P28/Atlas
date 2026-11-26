# Phase 9.4.1 — performance

## 1. What changed

Route-level code splitting in `web/src/App.tsx`: all sixteen pages load through `React.lazy`
behind one `Suspense` boundary. The shells, router, settings and shared primitives stay in the
entry chunk. This attacks the single 767 kB chunk reported in Phase 9.4 without changing any
calculation or data path.

## 2. Measured bundle, before and after

Same machine, same lockfile, `npm run build` (`tsc -b && vite build`).

| Measurement | Phase 9.4 (before) | Phase 9.4.1 (after) | Change |
| --- | --- | --- | --- |
| Entry JS | 767.15 kB (225.52 kB gzip) | **300.92 kB (94.22 kB gzip)** | −60.8 % raw, −58.2 % gzip |
| JS chunks | 1 | 24 | +23 |
| Total JS | 767.15 kB (225.52 kB gzip) | 754.36 kB (235.13 kB gzip) | −1.7 % raw, +4.3 % gzip |
| CSS | 57.46 kB (11.10 kB gzip) | 56.56 kB (11.78 kB gzip) | −1.6 % raw, +6.1 % gzip |
| Build time | 2.89 s | 2.93 s | +0.04 s |
| Vite >500 kB warning | present | **gone** | — |

Interpretation, stated honestly: the first screen an analyst sees now transfers roughly 94 kB of
compressed JavaScript instead of 226 kB. The total artifact is essentially unchanged and its
compressed total is slightly larger, because per-chunk overhead is real. Splitting therefore
improves time-to-first-view, not total download for a session that visits every page.

## 3. What was not measured

- Runtime timings (first paint, TTI, interaction latency), because the harness does not collect
  the browser performance timeline and adding one would be a new measurement path rather than a
  comparison.
- Workspace switch latency, docking/resize frame cost, memory.
- API request counts: the split does not change which requests a page makes; no panel fetches were
  added or removed in this phase.

No claim of interactive speedup is made. A smaller entry chunk is a transfer saving with a
plausible, unmeasured render-path benefit.

## 4. Regression risk

- 24 requests instead of 1 on a cold session that navigates everywhere; HTTP/2 multiplexing makes
  this cheap, HTTP/1.1 would not.
- The Suspense fallback is a plain status block: fast on this hardware, but it is a new network
  boundary and a slow disk can now show it where the old bundle showed nothing.
- Preloading is not implemented; hovering a nav link does not warm its chunk.

## 5. Reproduce

```bash
cd web && npm run build
python3 - <<'PY'
import os, gzip
root='dist/assets'
size=lambda fs:(sum(os.path.getsize(os.path.join(root,f)) for f in fs),
                sum(len(gzip.compress(open(os.path.join(root,f),'rb').read())) for f in fs))
js=[f for f in os.listdir(root) if f.endswith('.js')]
print(len(js), [round(x/1024,2) for x in size(js)])
print([round(x/1024,2) for x in size([f for f in js if f.startswith('index-')])])
PY
```
