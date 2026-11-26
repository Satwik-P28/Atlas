# Data licensing

Atlas is a research system that reads filings and market data. Software licensing and data
licensing are separate questions, and the release treats them that way.

## What the software licence covers

The Apache-2.0 licence applied to Atlas (root `LICENSE`, verbatim copy at
`licenses/Apache-2.0.txt`, `Copyright 2026 Satwik Peddireddi`) applies to Atlas's own source code,
tests, documentation and the project-authored synthetic filing under `fixtures/demo/**`. It grants
no right over any third-party dataset, and nothing in it should be read as doing so.

## What ships inside the distribution

| Content | Rights basis | Redistributable in the artifacts |
| --- | --- | --- |
| Atlas source code | Project-authored | Yes, under the software licence |
| Synthetic demonstration 10-K (`fixtures/demo/atlas-demo-10k.html`) | Project-authored | Yes |
| SEC-derived fixtures (`fixtures/sec/**`) | Derived facts, identifiers and digests of US government filings | Yes, as derived facts |
| Treasury yield and regulatory fixtures | Public domain / attribution recorded per path | Yes, with the attribution recorded in `DATA_RIGHTS_INVENTORY.json` |
| Frontend bundle | Atlas code plus npm dependencies under their own licences | Yes, with third-party notices |
| Vendor market prices (Nasdaq, Alpha Vantage) | Not permitted | **No** — not in the tree, not in the artifacts |

The authoritative per-path record is [`DATA_RIGHTS_INVENTORY.json`](DATA_RIGHTS_INVENTORY.json);
[`DATA_RIGHTS_AND_DISTRIBUTION.md`](DATA_RIGHTS_AND_DISTRIBUTION.md) explains the reasoning.

## What a user acquires at run time

Live SEC ingestion downloads filings from SEC EDGAR with the operator's own contact identity. SEC
filings are public records, but Atlas does not bundle downloaded filings:

- the Phase 10.5 real-filing acceptance fetches Apple's 10-K into a temporary directory, parses it,
  and deletes it with the temporary database;
- `atlas sec sync` stores derived facts, identifiers and document digests, not the filing text;
- a document a user ingests is classified `user_responsibility` by default, which keeps it local
  and blocks redistribution-bearing exports unless the operator records a different basis.

## What is not claimed

- No institutional data redistribution right is claimed for any vendor feed.
- No licence is claimed over SEC filings as documents; Atlas relies on the public-record status of
  the filings it fetches, and on derived facts for what it stores.
- A clean dependency scan or a licence inventory is not a legal opinion. The maintainer should have
  the final licensing decision reviewed before publication.
