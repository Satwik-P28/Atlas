# ADR 0014 — User data in SQLite with validated workspace documents

- **Status**: accepted (Phase 2)
- **Date**: 2026-11-04

## Context

Phase 2 adds the first mutable user state: watchlists, saved workspaces and interface
settings. It must survive restarts, reference stable security identities (not tickers),
never execute user-supplied code, and be shaped so a future hosted, multi-user Atlas does
not need a schema rewrite.

## Decision

Migration 003 (`phase2_terminal_user_data`) adds four tables, all owned by
`atlas/terminal/store.py`:

```sql
watchlist(watchlist_id, owner_id DEFAULT 'local', name, created_at, updated_at, UNIQUE(owner_id, name))
watchlist_item(watchlist_id, security_id, position, added_at, PRIMARY KEY(watchlist_id, security_id))
workspace(workspace_id, owner_id DEFAULT 'local', name, mode, columns, document_json,
          created_at, updated_at, UNIQUE(owner_id, name))
app_setting(owner_id, key, value_json, updated_at, PRIMARY KEY(owner_id, key))
```

Rules:

1. **Stable identities.** A watchlist item stores `security_id`; the ticker is joined for
   display. Renaming or reassigning a symbol cannot silently change a saved list, and the
   API rejects a ticker where a security id is required.
2. **Workspaces are data, not code.** The document is a typed JSON object:
   `{schema, name, description, mode, columns, panels[], indicator defaults}`. Panels have
   a registry-checked `type` (`chart`, `statements`, `metrics`, `xray`, `filings`,
   `events`, `notes`), integer `span` within `columns`, a referenced `security_id` /
   `issuer_id` / `evidence_id`, and a per-type config with a whitelist of keys. Unknown
   types, unknown keys, duplicate panel ids, spans wider than the grid and unknown
   indicator parameters are rejected with a 422. There is no expression evaluator, no
   template language and no script field.
3. **Server fills defaults.** `validate_workspace` normalises the document (default chart
   view, indicator defaults, columns). The stored `document_json` is the normalised form,
   so a workspace read back is byte-stable and `fingerprint` (SHA-256 of canonical JSON)
   identifies it.
4. **Presets are ordinary documents.** The three presets (Equity research, Technical
   analysis, Historical research) are produced by the same validator and can be edited
   like any saved workspace. Standard mode rejects advanced-only panel types server-side,
   not just in the UI.
5. **Owner column now, auth later.** `owner_id` defaults to `'local'`. Every query is
   written with an owner scope so adding authentication is a matter of passing a real
   subject and enforcing it at the HTTP boundary; the current API is loopback-only and
   does not claim to be multi-tenant.
6. **Settings are a whitelist.** `theme` and `mode` only, with enumerated values. Settings
   are preferences, never a way to inject configuration into the server.
7. **Names are unique per owner.** Duplicate creation is a 409 `storage_error` with the
   conflicting name, not a silent overwrite.

## Consequences

* Watchlist/workspace CRUD is tested across two independent app instances on the same
  file, so "persistence" means the database, not process memory.
* Deleting a watchlist cascades its items; deleting a security is prevented by existing
  Phase 1 references, so an orphaned item cannot occur.
* The workspace editor supports add/remove/reorder/resize/save/restore with explicit
  controls; drag-and-drop is not implemented and is not implied by the schema.
* A future multi-user deployment still needs authentication, per-owner quotas and a
  migration to copy the `local` rows to a real owner. The schema does not anticipate
  sharing/permissions; those would be new tables, not a change to these.
