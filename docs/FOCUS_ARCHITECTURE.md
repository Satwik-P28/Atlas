# FOCUS architecture

## Flagship chain

```text
SEC EDGAR 10-K HTML
        │
        ▼
KnowledgeEngine.ingest_document  ──► SQLite (availability, units, tables, hashes)
        │
        ▼
table_cells.extract_cells  ──► verified | unresolved (period, scale, currency, coords)
        │
        ▼
ConceptResolver.resolve  ──► one cell or refusal (statement family + scope)
        │
        ▼
bind(ResolvedFinancialInput)  ──► immutable evidence identity
        │
        ▼
FinancialAnswerEngine.*_bound + validate_binding
        │
        ├──────────────► FEC compile/execute
        │
        └──────────────► financial_verification (Fraction)
                         │
                         ▼ agree?
                    answered packet
                         │
                         ▼
              atlas.research_certificate.v1
                         │
                         ▼
              atlas verify-certificate  (no answer engine / no FEC)
```

## Why each subsystem exists

| Subsystem | Role |
|-----------|------|
| Knowledge store | Point-in-time document bytes, unit hashes, availability |
| Cell extractor | Refuse ambiguous geometry instead of guessing periods |
| Concept resolver | Map research intent to one statement cell; refuse conflicts |
| Binding | Prevent a second corpus-wide label search from replacing the selection |
| FEC | Typed operator graph with execution fingerprints |
| Fraction verifier | Independent arithmetic check |
| Certificate | Portable proof object for external examination |

## Diagram (source identity)

```text
Question + cutoff
    → concept key
    → candidate cells (period ∩ verified)
    → score (alias, statement family, consolidated scope, companions)
    → exact-alias preference
    → vintage conflict check
    → ResolvedFinancialInput
```

## Verification boundary

The production path may use FEC. The certificate verifier must not. It recomputes fingerprints and Fraction arithmetic from the certificate’s printed raw values and reports limitations when trusted source bytes are absent.
