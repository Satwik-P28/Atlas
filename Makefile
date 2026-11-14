# Atlas Quant — developer tasks
#
# Everything here is offline except `sync-live`, which requires network access and a
# contact User-Agent as required by SEC fair-access policy.

PYTHON ?= python3
VENV   ?= .venv
BIN     = $(VENV)/bin
DB     ?= var/atlas.db
CIK    ?= 320193
FOCUS_DB       ?= var/phase9_6.db
FOCUS_SNAPSHOTS ?= var/focus/snapshots
CERT   ?=

.PHONY: help install test demo bench cli-init sync sync-live facts history reconcile deps validate stats clean terminal-data serve web-install web-build phase8-fixtures phase8-bench release-manifest app-test focus-corpus focus-cases focus-demo focus-manifest focus-verify

help:
	@echo "install    create the virtualenv and install the package (editable, dev extras)"
	@echo "test       run the full offline test suite (186 tests)"
	@echo "demo       run the offline end-to-end demonstration"
	@echo "focus-corpus  build the FOCUS corpus from live SEC 10-Ks (needs ATLAS_SEC_USER_AGENT)"
	@echo "focus-cases   run the thirteen FOCUS financial cases against that corpus"
	@echo "focus-demo    run the full source-bound demonstration and write artifacts/focus_demo.json"
	@echo "focus-manifest  regenerate the pinned source manifest from the corpus"
	@echo "focus-verify  verify a certificate: make focus-verify CERT=path/to/cert.json"
	@echo "bench      run the reproducible benchmark suite"
	@echo "cli-init   create/migrate the database at $(DB)"
	@echo "sync       ingest a company from archived fixtures (CIK=$(CIK), no network)"
	@echo "sync-live  ingest a company from SEC EDGAR (needs ATLAS_SEC_USER_AGENT)"
	@echo "facts      show point-in-time facts for CIK=$(CIK)"
	@echo "history    report SEC filing-archive coverage for CIK=$(CIK)"
	@echo "reconcile  verify stored facts against the source payload for CIK=$(CIK)"
	@echo "deps       inspect the derived-computation dependency index"
	@echo "terminal-data  build var/atlas.db with 4 SEC issuers + synthetic market series"
	@echo "serve      run the terminal API on 127.0.0.1:8000"
	@echo "phase8-fixtures  rebuild the pinned .atlas package and domain pack"
	@echo "phase8-bench  measure package build/install/verify/execute"
	@echo "release-manifest  hash release files and emit an SBOM"
	@echo "app-test  run only the Phase 8 application contract tests"
	@echo "web-build  build the React terminal into web/dist"
	@echo "validate   run dataset integrity checks"
	@echo "stats      dataset and ingestion statistics"
	@echo "clean      remove the virtualenv, demo database and benchmark output"

install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --quiet --upgrade pip
	$(BIN)/python -m pip install --quiet -e ".[dev]"

test:
	$(BIN)/python -m pytest -q

demo:
	$(BIN)/atlas demo

# --------------------------------------------------------------------------- FOCUS
# Two distinct procedures, never conflated:
#   focus-corpus needs the network and a declared SEC contact User-Agent.
#   focus-demo   is offline given that corpus; it authenticates against archived bytes.

focus-corpus:
	@test -n "$$ATLAS_SEC_USER_AGENT" || (echo "set ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com'" && exit 1)
	$(BIN)/python scripts/focus_corpus.py --db $(FOCUS_DB) --snapshots $(FOCUS_SNAPSHOTS) --force

focus-cases:
	$(BIN)/python scripts/focus_demo.py --db $(FOCUS_DB) --quiet --out benchmarks/out/focus_demo.json

focus-demo:
	$(BIN)/python scripts/focus_demo.py --db $(FOCUS_DB) --snapshots $(FOCUS_SNAPSHOTS)

focus-manifest:
	$(BIN)/python scripts/focus_demo.py --db $(FOCUS_DB) --emit-manifest --quiet --out benchmarks/out/focus_demo.json

focus-verify:
	@test -n "$(CERT)" || (echo "usage: make focus-verify CERT=path/to/certificate.json" && exit 1)
	$(BIN)/atlas certificate verify --certificate $(CERT) --manifest artifacts/focus_source_manifest.json --snapshots $(FOCUS_SNAPSHOTS)

bench:
	$(BIN)/python benchmarks/bench.py --json benchmarks/out/bench.json

cli-init:
	$(BIN)/atlas --db $(DB) init

sync:
	$(BIN)/atlas --db $(DB) sec sync --cik $(CIK) --offline fixtures/sec

sync-live:
	@test -n "$$ATLAS_SEC_USER_AGENT" || (echo "set ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com'" && exit 1)
	$(BIN)/atlas --db $(DB) sec sync --cik $(CIK)

facts:
	$(BIN)/atlas --db $(DB) facts --cik $(CIK) --statement income

history:
	$(BIN)/atlas --db $(DB) sec history --cik $(CIK)

reconcile:
	$(BIN)/atlas --db $(DB) reconcile --cik $(CIK) --offline fixtures/sec

deps:
	$(BIN)/atlas --db $(DB) deps

terminal-data:
	$(PY) scripts/build_terminal_db.py --db $(DB) --force

serve:
	$(BIN)/atlas --db $(DB) serve --port 8000

web-install:
	cd web && npm install

web-build:
	cd web && npm run build

phase8-fixtures:
	$(BIN)/python scripts/build_phase8_fixtures.py

phase8-bench:
	$(BIN)/python scripts/benchmark_phase8.py --iterations 3

release-manifest:
	$(BIN)/python scripts/release_manifest.py

app-test:
	$(BIN)/python -m pytest -o addopts='' -q -p no:warnings tests/test_phase8_applications.py

validate:
	$(BIN)/atlas --db $(DB) validate

stats:
	$(BIN)/atlas --db $(DB) stats

clean:
	rm -rf $(VENV) var benchmarks/out .pytest_cache .hypothesis
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
