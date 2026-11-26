# Platform compatibility matrix

What was executed, on which platform, from which artifact. A blank cell is not a support claim; it
means the configuration was not run. Artifacts are the post-licence build from commit `36c7ee8`
(wheel `0d546263…`, sdist `aa29c862…`).

## Python runtime and packaging

| Platform | Python | Artifact | Checks | Result |
| --- | --- | --- | --- | --- |
| Linux x86-64 | 3.12.3 | wheel `atlas_quant-0.2.0b1` | install into clean venv, `init`, `doctor`, `demo`, `serve` health, MCP handshake (`scripts/verify_packaged_install.py`) | **PASS** (2026-11-26, this build) |
| Linux x86-64 | 3.12.3 | wheel | full real-SEC journey, 45/45 steps | **PASS** (2026-11-26) |
| Ubuntu (GitHub runner) | 3.12 | wheel built in CI | packaged-wheel job in hosted CI | **PASS** (run `45883811438`) |
| Windows (GitHub runner) | 3.12 | wheel built in CI | packaged-wheel job in hosted CI | **PASS** (run `45883811438`) |
| macOS (GitHub runner) | 3.12 | wheel built in CI | packaged-wheel job in hosted CI | **PASS** (run `45883811438`) |
| Linux x86-64 | 3.12.3 | sdist `atlas_quant-0.2.0b1.tar.gz` | built, hashed and reproduced; installed indirectly through the source build | **PASS** for build/reproduction; not installed standalone on every platform |
| Any | 3.11 | — | — | **NOT SUPPORTED**: `numpy` publishes no 3.11 wheel for this range |

The platform matrix covers installation and the offline demonstration. The real SEC journey was
executed on Linux only; the hosted matrix certifies installation, not the network journey.

## Browsers

| Engine | Where | Viewports tested | Result |
| --- | --- | --- | --- |
| Chromium (headless shell 156) | local | 1440×900, 390×844 | **21 of 21 checks PASS** (`artifacts/browser/phase10_5_chromium.json`) |
| Chromium | hosted CI | 1440×900 | **PASS** (run `45883811438`, certification job) |
| Firefox | hosted CI | 1440×900 | **PASS** (run `45883811438`, certification job) |
| WebKit | hosted CI | 1440×900 | **PASS** (run `45883811438`, certification job) |
| Firefox / WebKit | local container | — | **NOT RUN** — no GTK/Pango stack and no root in the build container |
| Safari, Edge, mobile browsers | — | — | **NOT TESTED** |

No support claim is made beyond the 21-step journey. The responsive layout was checked at 390×844 in
Chromium only.

## Interfaces

| Surface | Verified |
| --- | --- |
| Browser UI | 21-step certification journey on Chromium, Firefox and WebKit (hosted) |
| HTTP API | Real-filing acceptance (45 steps) and offline acceptance (30 steps) |
| CLI | `atlas init`, `doctor`, `demo`, `sec sync`, `serve`, `verify-certificate`, MCP launch |
| MCP (stdio) | Official `mcp` Python SDK: 14 tools, structured content, typed refusals, read-only enforcement |
| Exports | PDF (text extracted and reconciled) and JSON (44 claims, 34/34 numeric figures present in the PDF) |
| Python imports | `numpy`, `tzdata`, `scipy`, `pyarrow`, `scikit-learn`, `fastapi`, `uvicorn`, `osqp`, `clarabel`, `mcp` all import in the certified environment |

## What is not covered

- Load testing beyond the bounded resource audit (200 invalid requests, 20 dropped connections, 4
  concurrent MCP sessions, peak RSS 109 MB).
- Any multi-user deployment: the service is unauthenticated and loopback-only by design.
- Windows and macOS real-SEC journeys.
- Byte identity of artifacts across different interpreters, setuptools or zlib versions.
