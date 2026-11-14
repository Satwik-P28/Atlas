# Engineering defence

Answers that a reviewer can check against the code. Each answer names the file that settles it.

---

**Why SQLite?**

Because the workload is single-writer, embedded, and needs transactional integrity over a document
corpus, not concurrent multi-node access. `src/atlas/storage/db.py` exposes a small surface
(`query`, `query_one`, `execute`, `transaction`, `migrate`) and
`src/atlas/storage/migrations.py` keeps an append-only, versioned schema with invariants declared in
SQL (uniqueness, foreign keys, checks) so a programming error cannot persist contradictory rows.
Migrations 1–15 are never edited once released; correcting a released schema means adding one.

The cost is real: no concurrent writers, and full-text search uses FTS5 rather than a dedicated
engine. For one analyst over four filings that is the correct trade. It would not be for a
multi-tenant service, and I would not claim it would be.

---

**Why a typed compiler instead of computing in Python?**

Because the failure I care about is combining incompatible quantities. `atlas/fec` compiles a plan
whose inputs carry types and executes it with exact decimal semantics; `financial_answers.py` builds
that plan from bound cells and never touches arithmetic itself. The benefit is not speed. It is
that the computation becomes a *recorded artifact* — the plan, the compiler version, the operator
version table, the model fingerprint and the execution trace all travel with the answer, so the
certificate can name exactly what ran.

---

**Why a second (and third) arithmetic implementation?**

Agreement of an implementation with itself proves nothing. `financial_verification.py` recomputes
from printed text with `Fraction` and shares no code with the compiler; the answer engine refuses
when they disagree (`verification_disagreement`). `certificate_verify.compute` is a third
implementation used by the verifier so that the verifier does not trust the process that produced
the artifact. The limit is explicit in the technical note: these protect the arithmetic, not the
extraction.

---

**How does source trust actually work?**

Four levels, in `certificate_verify.verify`:

1. `ARITHMETIC_VERIFIED` — payload is well formed, its fingerprint matches its body, and the
   verifier's own rational arithmetic over the inputs the certificate carries reproduces the result.
2. `SOURCE_VERIFIED` — additionally: the accession is pinned in a manifest, the manifest's document
   hash equals the certificate's, the original bytes hash to that value, the source table is located
   inside those bytes by content hash, the printed text at the recorded coordinates equals the
   claimed raw text, semantic fields match the manifest, and the arithmetic recomputed from the
   snapshot's text matches.
3. `SOURCE_UNVERIFIED` — arithmetic holds but authoritative evidence is missing, including the
   manifest-only case.
4. `INVALID` — a check failed.

A manifest alone deliberately does **not** reach level 2: a manifest cannot prove which bytes SEC
served.

---

**What does a fingerprint prove?**

That the payload has not changed since the digest was computed. Nothing else. An attacker who edits
an input and the result together and recomputes every owned hash produces a self-consistent forgery.
The demonstration runs exactly that case: `ARITHMETIC_VERIFIED` without evidence, `INVALID` with it.

---

**How are restatements and availability handled?**

Every document stores `availability_time`, `availability_precision` and `availability_basis`.
Availability is modelled conservatively as EDGAR acceptance plus a fixed lag, and precision is
recorded as `unknown` rather than claiming an exact public-release instant. Queries filter documents
by cutoff before cell extraction (`FinancialAnswerEngine.cells`), and `validate_binding` re-checks
availability against the store before any arithmetic. Case 13 is the test: a 2022 filing cannot
answer a 2017 query.

A genuine amendment (`/A`) is stored as a separate document with `is_amendment` and
`amends_accession`; nothing silently replaces the original.

---

**What is mathematically proven versus empirically tested?**

Proven by construction: the arithmetic is exact rational arithmetic with one quantisation step at
the output boundary; the fingerprint is a cryptographic digest of a canonical encoding; a certificate
with *n* evidence items cannot structurally claim a 2-operand operator.

Empirically tested: that the resolver picks the right row; that the parser reads the right column;
that scale is recovered; that currency is recovered. Every one of these has a case in this repository
where it failed at least once.

---

**What could cause the system to return a wrong answer?**

Ranked by what I would actually expect:

1. **Concept mapping.** The bytes prove the row labelled "Net sales" holds 34,229. They do not prove
   that "Net sales" is what the question meant. Pinned by a reviewed manifest, not proven.
2. **Extraction.** Verification re-runs the same parser over authenticated bytes. A parser that
   mis-associates a column yields a certificate with the wrong raw text — visible, but passing.
3. **Scale.** Demonstrated: 3M's in-table `(Millions, …)` row was ignored, producing a 10^6 error
   until fixed. Other filings may declare scale in a form still unrecognised.
4. **Currency.** Not detected at all for these statements. Currency is simply not claimed.

The mitigation for (1)–(3) is the same and is not complete: the printed raw text and the row/column
coordinates are in the certificate, so a human reviewing a certificate can see the claim.

---

**Which optimisation failed, or was not attempted?**

`FinancialAnswerEngine.cells` re-extracts every table of every document on each call; `focus-demo`
takes 18.60 s and 89 MiB for four filings. I did not memoise it, did not add columnar storage, and
did not rewrite anything in a faster language, because for a single-document demonstration there is
no measured reason to, and an unmeasured optimisation is a liability. If profiling later shows the
cost matters, the cache key has to include cutoff, parser version and document hash, otherwise it
would silently reuse computations across incompatible contexts.

---

**Why is this not just an LLM wrapper?**

There is no model in the answer path. `raise` if you disagree: `financial_answers.py` imports no
model client, and every number is traced to a row and column of a filing. The research question is
"how do you know", and the answer is a certificate plus independent evidence, not a sampled token.

---

**How would it scale?**

The bottlenecks are extraction (linear in tables) and the resolver's candidate scoring (linear in
cells for an issuer). Both are per-issuer and cacheable by content hash: the same table parsed twice
should be parsed once, keyed by table SHA-256 plus parser version. The store already separates
documents, units and tables by content hash, so the cache key is well defined. The hard part is not
throughput; it is that a cache keyed on anything less than (document hash, cutoff, parser version,
resolver version) would return answers computed under a different evidence context, which is exactly
the bug class the certificate exists to prevent.

---

**What would you build next?**

XBRL corroboration via SEC's `companyfacts`, keyed by accession and reporting context, treating
disagreement as a first-class outcome rather than a tiebreak. That is the shortest path from "the
row says 34,229" to "this row is the concept, and here is an independent structured source that
agrees". Custom inline XBRL tags frequently do not appear in `companyfacts`, so the interesting cases
are the conflicts, and the system must preserve them.

---

**What is the strongest limitation?**

That concept mapping is a judgement wearing a certificate's clothes. Everything around it is
mechanised — the bytes, the hashes, the coordinates, the arithmetic — and a reader can be forgiven
for assuming the whole chain is proven. The verifier prints this limitation on every
`SOURCE_VERIFIED` result precisely because it is the weakest link and the easiest to over-claim.
