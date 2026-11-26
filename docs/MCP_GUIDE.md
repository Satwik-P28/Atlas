# MCP: connecting an external assistant to Atlas

Atlas ships a real Model Context Protocol server (`atlas mcp`). It speaks JSON-RPC 2.0 over
stdio, exposes fourteen tools, and is **read-only by default**. It is a local process: it
binds no port, opens no network connection of its own, and cannot be reached from another
host.

```bash
atlas init                # create the database once
atlas demo                # or build the offline demonstration database
atlas mcp                 # serve MCP on stdin/stdout
atlas mcp --allow-mutations   # also allow saving a research object
```

Point any MCP client at the command `atlas mcp --db <path>`. Protocol versions
`2024-11-05` and `2025-06-18` are negotiated; the tool surface is identical.

## Tools

| Tool | What it returns |
| --- | --- |
| `search_companies` | Issuers in this database. Unknown symbols return an empty list. |
| `get_company_financials` | Point-in-time statements; every cell carries an evidence id, availability time and precision. |
| `search_filings` | Archived documents, or passages for a query at a cutoff. |
| `get_evidence` | Full provenance for one observation, including its revision chain. |
| `resolve_financial_question` | Exactly one verified consolidated cell for a concept and period, or a refusal with candidates. |
| `verify_financial_answer` | Independent verification of a certificate: identity, availability, types, arithmetic, fingerprints. |
| `compare_companies` | Two issuers' statements, enforcing identical row definitions, units and period ends. |
| `inspect_model` | Allowlisted FEC operators with version, arity and formula. |
| `run_supported_model` | Compile and execute an `atlas.model.v1` spec against typed inputs. |
| `run_scenario` | DCF base/bull/bear (or caller overrides) with the assumptions that produced each value. |
| `get_research_workspace` | One saved research object exactly as stored. |
| `verify_research_artifact` | Recompute a canonical content hash and check that cited evidence exists. |
| `inspect_data_health` | Schema version, SQLite integrity and table counts. |
| `save_research_object` | Persist a versioned research object — refused unless `--allow-mutations`. |

## Guarantees an integration can rely on

1. **Provenance.** Every financial value returns its document id, accession, table, cell
   coordinates, row and column labels, currency, scale and availability semantics. A tool
   never returns a bare number.
2. **Refusal is an answer.** An ambiguous or unresolvable concept returns
   `answered: false` with the reason and the candidates Atlas considered. It never
   approximates.
3. **Estimated availability is labelled.** A document whose public-release instant was
   modelled (EDGAR acceptance plus a publication lag) is reported with
   `is_estimated: true` and precision `unknown`. That bound may exclude evidence; it must
   never be quoted as a verified release instant.
4. **Typed, strict arguments.** Unknown fields are refused rather than ignored, so a
   misspelled `as_of` cannot silently return the latest data.
5. **Bounded execution.** Each call has a deadline (`--call-timeout`, default 20 s), result
   size is capped, and documents from the caller are size-limited.
6. **No execution surface.** No tool accepts SQL, a shell command, a filesystem path or a
   URL. Retrieved filing text is data, never an instruction.
7. **No secrets.** No tool accepts, stores or returns a credential.

## Errors

- JSON-RPC parse/validation failures return `-32700`, `-32600`, `-32602`.
- An unknown method returns `-32601`; a cancelled request returns `-32800`.
- A tool that fails for a caller-actionable reason returns a normal result with
  `isError: true` and `structuredContent.error.code` (`authorization_required`,
  `tool_timeout`, `result_too_large`, `document_too_large`, or a domain code such as
  `unknown_issuer`).

## What this server is not

It is not an oracle. A verified cell is verified against its source table; the economic
interpretation of that cell is still the analyst's judgement. `verify_financial_answer`
establishes internal consistency and, with pinned source bytes, source identity — never
that the interpretation is correct.
