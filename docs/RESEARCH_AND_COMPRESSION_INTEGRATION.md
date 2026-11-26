# Research and compression integration contract (Phase 9.2.8)

This document establishes the **integration and evaluation contract** for Master
Specification Sections 49 (Financial Knowledge Engine), 50 (compression / CDG),
53 (Resource Optimization Engine) and 57 (ResearchOS programme). It does not implement any
of them, and it makes no claim that any of them improves anything.

## 1. Status of the claims

| Claim in the specification | Status | Treatment here |
| --- | --- | --- |
| A unified retrieval layer can answer financial questions with exact source support | **hypothesis** | Evaluated against lexical/hybrid baselines before adoption |
| Compression can reduce total source + index + cache + transfer bytes | **hypothesis** | Byte accounting includes every copy, not just the encoded object |
| Compressed representations can reconstruct the original exactly | **requirement**, not yet proven | Byte-exact reconstruction with hashes is a hard gate |
| An adaptive resource policy beats fixed policies at equal quality | **hypothesis** | Measured against fixed policies on shifted workloads |
| Research results are academically defensible | **process requirement** | Pre-registration, replication and negative results |

Atlas already stores the evidence these systems would consume; it does not yet retrieve,
compress, or optimize over it.

## 2. What already exists and must not be disturbed

| Capability | Module | Property that constrains any adapter |
| --- | --- | --- |
| Immutable raw documents with SHA-256 and retrieval metadata | `src/atlas/evidence/model.py`, `src/atlas/evidence/kernel.py` | A document is addressed by content hash; nothing may rewrite stored bytes |
| Point-in-time selection with availability semantics | `src/atlas/evidence/kernel.py` | Any index must answer as-of a cutoff, including revisions and supersessions |
| Observation identity and replay pins | `src/atlas/research/observations.py`, `src/atlas/market/evidence.py` | `observation_id`/`content_hash` are stable; an index that changes them breaks saved research |
| Portable application packages | `src/atlas/applications`, `src/atlas/research/archive.py` | Reproduction depends on deterministic archive bytes |
| Rights classification | `src/atlas/research/rights.py`, `src/atlas/storage/sources.py` | A retrieval index inherits the strictest right of its content and must not leak restricted text |

**Hard boundary:** no experimental format may sit on the authoritative SEC document path.
Experiments read stored bytes and write only to an experimental side store. If a byte on the
authoritative path changes, the experiment has failed its contract regardless of speed.

## 3. Where experimental adapters can live

| Adapter | Host module (read-only) | Writes to |
| --- | --- | --- |
| Chunk/span index over filings | `atlas/evidence/kernel.py` (`as_of` reads) | new experimental tables, never `evidence` |
| Compression codec | `atlas/research/archive.py` (bytes in, bytes out) | experimental store |
| Retrieval baseline harness | `atlas/research/objects.py` (object references as keys) | evaluation artefacts |
| Cost/latency instrumentation | `atlas/terminal/market_projection.py` pattern (plan switch, differential test) | benchmark artefacts |
| Policy comparison | `atlas/terminal/cache.py`, `metric_store.py` | no production policy change until measured |

Each adapter must expose a `plan`-style switch so the existing path remains the reference
implementation and equivalence is testable, exactly as Phase 9.2.8 did for the market
projection.

## 4. Evaluation plan (pre-registered)

### 4.1 Corpora

* Financial filings already archived under `fixtures/` (public domain), stratified by form
  type, revision status and table density.
* An independent finance QA set with gold spans, built before looking at retrieval results.
* A non-financial control corpus, to test Section 57's generalisation claim.
* Adversarial revision pairs: footnotes, negations, deleted numbers, restated figures.

### 4.2 Baselines (all must be run)

1. Exact keyword search.
2. BM25 lexical ranking.
3. Hybrid lexical + dense retrieval with a published embedding model.
4. No-retrieval (abstain always), to price the cost of guessing.

### 4.3 Metrics

| Dimension | Metric | Gate |
| --- | --- | --- |
| Retrieval | recall@k, MRR, correct-version recall | Report per stratum, not just aggregate |
| Grounding | answer accuracy with span support, numeric exactness | A wrong number is a failure, not a partial credit |
| Abstention | abstention precision/recall on unanswerable questions | Must not abstain on answerable questions to look safe |
| Conflicts | conflict detection rate | Must surface, never average, contradictory sources |
| Compression | total bytes (source + index + cache + transfer) | All copies counted |
| Reconstruction | byte-exact recovery, hash match | Hard gate; any mismatch fails |
| Corruption | safe failure and recovery on truncation/bit flips | No silent partial reconstruction |
| Cost | p95 latency, peak memory, index build time, CPU-only | Published with hardware |
| Quality-neutrality | quality at equal budget vs baseline | Improvement must be quality-matched |

### 4.4 Resource budgets

* Storage: index + experimental store must be reported separately from the evidence store.
* Compute: CPU-only must complete every evaluation; GPU is an optimisation, not a dependency.
* Latency: interactive retrieval p95 target set by measurement, not asserted in advance.
* Budgets are recorded per corpus size so a result cannot be generalised from a toy corpus.

## 5. Sequencing and kill criteria

1. Baseline harness and gold sets (no encoder).
2. Retrieval only; compression deferred until retrieval evaluation is stable.
3. Compression with byte-exact reconstruction and corruption tests.
4. Joint search/cost frontier against baselines.
5. Resource-policy experiments on shifted workloads (Section 53).
6. Generalisation study across corpora (Section 57).

Kill criteria, agreed before running: if correct-version recall or grounded accuracy is
below the lexical/hybrid baseline at equal cost, the representation is rejected for that
scope; if reconstruction is not byte-exact, it is rejected outright; if the gain does not
replicate on the control corpus, the generalisation claim is withdrawn and recorded.

## 6. What Phase 9.2.8 does **not** claim

* No encoder, index, retriever or policy engine exists.
* No RAG improvement has been demonstrated, because no grounded QA evaluation has been run.
* No compression ratio is claimed; the specification's byte accounting is a hypothesis.
* No experimental format has been placed on the authoritative document path.
