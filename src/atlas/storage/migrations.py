"""Versioned schema migrations.

The schema is append-only: migrations are never edited once released, because a
released migration may already have been applied to a user's database. Correcting
a released schema means adding a new migration.

Migration ``001`` is the Phase 1 foundation. Every table declares its invariants in
SQL where possible (uniqueness, foreign keys, checks) so that a programming error
cannot quietly persist contradictory data.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.errors import MigrationError


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


_MIGRATION_001 = """
-- ===========================================================================
-- Phase 1 foundation schema
-- ===========================================================================

CREATE TABLE source (
    source_id        TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    kind             TEXT NOT NULL,   -- sec_edgar | csv_import | synthetic | manual
    homepage         TEXT,
    licence          TEXT,
    redistribution   TEXT NOT NULL DEFAULT 'restricted',
    notes            TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE raw_document (
    doc_id          TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES source(source_id),
    url             TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    media_type      TEXT,
    http_status     INTEGER,
    byte_size       INTEGER NOT NULL,
    retrieved_at    TEXT NOT NULL,
    etag            TEXT,
    last_modified   TEXT,
    body            BLOB NOT NULL,
    UNIQUE (source_id, content_hash)
);
CREATE INDEX idx_raw_document_url ON raw_document (url, retrieved_at DESC);

-- --------------------------------------------------------------------------
-- Entity master
-- --------------------------------------------------------------------------
CREATE TABLE issuer (
    issuer_id          TEXT PRIMARY KEY,
    cik                TEXT UNIQUE,
    legal_name         TEXT NOT NULL,
    entity_type        TEXT,
    domicile_country   TEXT,
    sic                TEXT,
    fiscal_year_end    TEXT,
    is_active          INTEGER NOT NULL DEFAULT 1,
    provenance_source  TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE security (
    security_id        TEXT PRIMARY KEY,
    issuer_id          TEXT NOT NULL REFERENCES issuer(issuer_id),
    security_type      TEXT NOT NULL,      -- common_stock | preferred | adr | etf | ...
    class_designation  TEXT NOT NULL,      -- human-readable share class
    share_class_key    TEXT NOT NULL,      -- canonical key used for id derivation
    currency           TEXT,
    is_active          INTEGER NOT NULL DEFAULT 1,
    first_observed_at  TEXT,
    last_observed_at   TEXT,
    note               TEXT,
    UNIQUE (issuer_id, share_class_key)
);

CREATE TABLE venue (
    mic          TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    country      TEXT,
    timezone     TEXT NOT NULL
);

CREATE TABLE listing (
    listing_id   TEXT PRIMARY KEY,
    security_id  TEXT NOT NULL REFERENCES security(security_id),
    mic          TEXT NOT NULL REFERENCES venue(mic),
    currency     TEXT,
    valid_from   TEXT,
    valid_to     TEXT,
    is_primary   INTEGER NOT NULL DEFAULT 0,
    source_id    TEXT REFERENCES source(source_id),
    UNIQUE (security_id, mic, valid_from)
);

-- A ticker is a time-bounded property of a listing, never part of a security id.
CREATE TABLE ticker_assignment (
    ticker_assignment_id  TEXT PRIMARY KEY,
    listing_id            TEXT NOT NULL REFERENCES listing(listing_id),
    ticker                TEXT NOT NULL,
    valid_from            TEXT NOT NULL,
    valid_to              TEXT,
    confidence            REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status                TEXT NOT NULL,   -- confirmed | probable | unverified | retracted
    source_id             TEXT REFERENCES source(source_id),
    evidence_note         TEXT,
    created_at            TEXT NOT NULL,
    UNIQUE (ticker, valid_from, listing_id),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX idx_ticker_assignment_lookup ON ticker_assignment (ticker, valid_from, valid_to);

CREATE TABLE security_identifier (
    assignment_id  TEXT PRIMARY KEY,
    security_id    TEXT NOT NULL REFERENCES security(security_id),
    scheme         TEXT NOT NULL,      -- CIK | ISIN | FIGI | CUSIP | VENDOR:...
    value          TEXT NOT NULL,
    valid_from     TEXT,
    valid_to       TEXT,
    confidence     REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status         TEXT NOT NULL,
    source_id      TEXT REFERENCES source(source_id),
    licence_note   TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE (scheme, value, valid_from)
);
CREATE INDEX idx_security_identifier_value ON security_identifier (scheme, value);

CREATE TABLE entity_relationship (
    relationship_id    TEXT PRIMARY KEY,
    from_issuer_id     TEXT NOT NULL REFERENCES issuer(issuer_id),
    to_issuer_id       TEXT NOT NULL REFERENCES issuer(issuer_id),
    relationship_type  TEXT NOT NULL,  -- subsidiary | parent | merger_successor | spin_off_parent
    valid_from         TEXT,
    valid_to           TEXT,
    confidence         REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    source_id          TEXT REFERENCES source(source_id),
    note               TEXT,
    CHECK (from_issuer_id <> to_issuer_id)
);

-- --------------------------------------------------------------------------
-- Trading calendar
-- --------------------------------------------------------------------------
CREATE TABLE trading_session (
    mic            TEXT NOT NULL REFERENCES venue(mic),
    session_date   TEXT NOT NULL,   -- YYYY-MM-DD in the venue's local calendar
    open_ts        TEXT NOT NULL,   -- UTC instant
    close_ts       TEXT NOT NULL,
    is_early_close INTEGER NOT NULL DEFAULT 0,
    source_id      TEXT REFERENCES source(source_id),
    PRIMARY KEY (mic, session_date)
);

-- --------------------------------------------------------------------------
-- SEC filings
-- --------------------------------------------------------------------------
CREATE TABLE filing (
    filing_id            TEXT PRIMARY KEY,
    issuer_id            TEXT REFERENCES issuer(issuer_id),
    cik                  TEXT NOT NULL,
    accession_number     TEXT NOT NULL UNIQUE,
    form_type            TEXT NOT NULL,
    filed_date           TEXT NOT NULL,
    acceptance_datetime  TEXT,
    period_of_report     TEXT,
    primary_document     TEXT,
    is_amendment         INTEGER NOT NULL DEFAULT 0,
    amends_accession     TEXT,
    is_xbrl             INTEGER,
    is_inline_xbrl      INTEGER,
    doc_id               TEXT REFERENCES raw_document(doc_id),
    source_id            TEXT REFERENCES source(source_id)
);
CREATE INDEX idx_filing_cik_date ON filing (cik, filed_date);

-- --------------------------------------------------------------------------
-- Temporal evidence kernel
-- --------------------------------------------------------------------------
CREATE TABLE evidence (
    evidence_id              TEXT PRIMARY KEY,
    record_kind              TEXT NOT NULL,  -- financial_fact | market_metadata | ...
    entity_id                TEXT NOT NULL,  -- issuer_id or security_id (see entity_kind)
    entity_kind              TEXT NOT NULL,  -- issuer | security
    concept                  TEXT NOT NULL,  -- canonical Atlas concept key
    source_id                TEXT NOT NULL REFERENCES source(source_id),
    source_url               TEXT,
    source_dataset           TEXT,
    source_dataset_version   TEXT,
    taxonomy                 TEXT,            -- e.g. us-gaap
    source_concept           TEXT,            -- original tag, unmodified
    value_numeric            TEXT,            -- canonical decimal string
    value_text               TEXT,
    unit                     TEXT NOT NULL,
    unit_kind                TEXT NOT NULL,
    currency                 TEXT,
    period_start             TEXT,
    period_end               TEXT,
    period_type              TEXT,
    fiscal_year              INTEGER,
    fiscal_period            TEXT,
    valid_from               TEXT,
    valid_to                 TEXT,
    availability_time        TEXT,
    availability_precision   TEXT NOT NULL,
    availability_basis       TEXT,
    filed_date               TEXT,
    acceptance_datetime      TEXT,
    observed_at             TEXT NOT NULL,
    -- Monotonic ingestion order. Availability timestamps can tie (a correction filed
    -- with the same acceptance time); ingestion order is then the only honest
    -- tie-break, and it also underpins the "what had Atlas ingested" question.
    ingest_seq               INTEGER NOT NULL DEFAULT 0,
    content_hash             TEXT NOT NULL,
    original_record_hash     TEXT,
    raw_doc_id               TEXT REFERENCES raw_document(doc_id),
    accession_number         TEXT,
    form_type                TEXT,
    revision_kind            TEXT NOT NULL,  -- original | amendment | restatement | correction
    supersedes               TEXT REFERENCES evidence(evidence_id),
    derivation_kind          TEXT NOT NULL,  -- source_observation | normalized_source_observation
                                             -- | derived_calculation | estimate
    derivation_rule          TEXT,
    transformation_lineage   TEXT,           -- JSON array of applied steps
    quality                  TEXT NOT NULL,  -- verified | unverified | suspect | quarantined
    verification             TEXT NOT NULL,  -- source_primary | source_secondary | cross_validated | unchecked
    limitations              TEXT,
    UNIQUE (content_hash)
);
CREATE INDEX idx_evidence_lookup ON evidence (entity_id, concept, period_end, unit);
CREATE INDEX idx_evidence_availability ON evidence (availability_time);
CREATE INDEX idx_evidence_observed ON evidence (observed_at);
CREATE INDEX idx_evidence_supersedes ON evidence (supersedes);
CREATE INDEX idx_evidence_accession ON evidence (accession_number);
CREATE INDEX idx_evidence_raw_doc ON evidence (raw_doc_id);

CREATE TABLE evidence_supersession (
    superseded_id   TEXT NOT NULL REFERENCES evidence(evidence_id),
    superseding_id  TEXT NOT NULL REFERENCES evidence(evidence_id),
    reason          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (superseded_id, superseding_id),
    CHECK (superseded_id <> superseding_id)
);

-- --------------------------------------------------------------------------
-- Market data
-- --------------------------------------------------------------------------
-- Raw bars are immutable. A provider correction appends a new revision_seq row and
-- sets supersedes_bar, so the original observation is never lost.
CREATE TABLE bar (
    security_id        TEXT NOT NULL REFERENCES security(security_id),
    mic                TEXT NOT NULL REFERENCES venue(mic),
    interval           TEXT NOT NULL,          -- 1d, 1m, ...
    ts_utc             TEXT NOT NULL,
    revision_seq       INTEGER NOT NULL DEFAULT 1,
    open               TEXT NOT NULL,
    high               TEXT NOT NULL,
    low                TEXT NOT NULL,
    close              TEXT NOT NULL,
    volume             TEXT,
    trades             INTEGER,
    vwap               TEXT,
    currency           TEXT NOT NULL,
    adjustment_status  TEXT NOT NULL,          -- raw | split_adjusted | total_return_adjusted
    source_id          TEXT NOT NULL REFERENCES source(source_id),
    observed_at        TEXT NOT NULL,
    ingested_at        TEXT NOT NULL,
    supersedes_bar     INTEGER,
    quality_flags      TEXT,                   -- JSON array
    PRIMARY KEY (security_id, mic, interval, ts_utc, source_id, revision_seq)
);
CREATE INDEX idx_bar_query ON bar (security_id, mic, interval, ts_utc);

CREATE TABLE corporate_action (
    action_id                TEXT PRIMARY KEY,
    security_id              TEXT NOT NULL REFERENCES security(security_id),
    action_type              TEXT NOT NULL,   -- split | reverse_split | cash_dividend | ticker_change
                                              -- | merger | spin_off | distribution (declared, not computed)
    ex_date                  TEXT,
    effective_date           TEXT,
    record_date              TEXT,
    payable_date             TEXT,
    ratio_from               TEXT,
    ratio_to                 TEXT,
    cash_amount              TEXT,
    currency                 TEXT,
    terms_json               TEXT,
    status                   TEXT NOT NULL,   -- announced | confirmed | corrected | cancelled | provisional
    confidence               REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
    source_id                TEXT NOT NULL REFERENCES source(source_id),
    evidence_id              TEXT REFERENCES evidence(evidence_id),
    availability_time        TEXT,
    availability_precision   TEXT,
    observed_at              TEXT NOT NULL,
    supersedes               TEXT REFERENCES corporate_action(action_id),
    notes                    TEXT
);
CREATE INDEX idx_corporate_action_security ON corporate_action (security_id, ex_date);

-- --------------------------------------------------------------------------
-- Operations
-- --------------------------------------------------------------------------
CREATE TABLE data_quality_issue (
    issue_id     TEXT PRIMARY KEY,
    scope        TEXT NOT NULL,
    subject_id   TEXT,
    code         TEXT NOT NULL,
    severity     TEXT NOT NULL,   -- info | warning | error
    detail       TEXT NOT NULL,
    detected_at  TEXT NOT NULL,
    resolved_at  TEXT,
    UNIQUE (scope, subject_id, code, detail)
);
CREATE INDEX idx_dqi_unresolved ON data_quality_issue (resolved_at, severity);

CREATE TABLE ingestion_run (
    run_id       TEXT PRIMARY KEY,
    command      TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,   -- running | completed | failed | interrupted
    stats_json   TEXT,
    error        TEXT,
    resumable    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE sync_checkpoint (
    checkpoint_key  TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""


_MIGRATION_002 = """
-- ===========================================================================
-- Phase 1.1 hardening: submissions history + reverse dependency index
-- ===========================================================================

-- One row per fetched SEC submissions *history archive* (the files listed in
-- ``filings.files``). Tracking the content hash makes history sync incremental:
-- an archive whose bytes are unchanged is not re-parsed. It is also the evidence
-- that Atlas knows the filing list is complete rather than merely recent.
CREATE TABLE submissions_file (
    cik             TEXT NOT NULL,
    name            TEXT NOT NULL,
    advertised_count INTEGER,
    advertised_from TEXT,
    advertised_to   TEXT,
    filing_rows     INTEGER NOT NULL DEFAULT 0,
    content_hash    TEXT NOT NULL,
    doc_id          TEXT REFERENCES raw_document(doc_id),
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (cik, name)
);
CREATE INDEX idx_submissions_file_cik ON submissions_file (cik, fetched_at);

-- Reverse dependency index. A derived evidence record was produced by exactly one
-- computation; ``computation_input`` names every evidence record that computation
-- consumed. Together they answer "which derived values depend on this evidence?"
-- without re-deriving anything, and they are the join the Phase 2 compiler needs to
-- invalidate stale outputs. Atlas stores lineage on the evidence record already;
-- these tables are the indexed projection of that lineage.
CREATE TABLE computation (
    computation_id   TEXT PRIMARY KEY,
    rule_id          TEXT NOT NULL,
    output_evidence  TEXT NOT NULL UNIQUE REFERENCES evidence(evidence_id),
    knowledge_as_of  TEXT,
    mode             TEXT,
    engine           TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX idx_computation_rule ON computation (rule_id);

CREATE TABLE computation_input (
    computation_id TEXT NOT NULL REFERENCES computation(computation_id),
    evidence_id    TEXT NOT NULL REFERENCES evidence(evidence_id),
    role           TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (computation_id, evidence_id, role)
);
CREATE INDEX idx_computation_input_evidence ON computation_input (evidence_id);
"""


_MIGRATION_003 = """
-- ===========================================================================
-- Phase 2 terminal: saved watchlists, workspaces and preferences
-- ===========================================================================

-- User data is deliberately separate from the evidence layer. A watchlist is a
-- view preference, not a claim about a company, so it never creates evidence and
-- cannot affect a point-in-time answer. ``owner_id`` exists so multi-user support
-- is an additive change later; local operation always uses 'local'.
CREATE TABLE watchlist (
    watchlist_id TEXT PRIMARY KEY,
    owner_id     TEXT NOT NULL DEFAULT 'local',
    name         TEXT NOT NULL COLLATE NOCASE,
    notes        TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (owner_id, name)
);

-- Items reference stable security ids, never tickers: a symbol can be reassigned
-- and a saved list must not silently change meaning.
CREATE TABLE watchlist_item (
    watchlist_id TEXT NOT NULL REFERENCES watchlist(watchlist_id) ON DELETE CASCADE,
    security_id  TEXT NOT NULL REFERENCES security(security_id),
    position     INTEGER NOT NULL DEFAULT 0,
    added_at     TEXT NOT NULL,
    PRIMARY KEY (watchlist_id, security_id)
);
CREATE INDEX idx_watchlist_item_security ON watchlist_item (security_id);

CREATE TABLE workspace (
    workspace_id   TEXT PRIMARY KEY,
    owner_id       TEXT NOT NULL DEFAULT 'local',
    name           TEXT NOT NULL COLLATE NOCASE,
    mode           TEXT NOT NULL,
    columns        INTEGER NOT NULL DEFAULT 3,
    schema_version TEXT NOT NULL DEFAULT 'atlas.workspace.v1',
    config_json    TEXT NOT NULL,
    fingerprint    TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE (owner_id, name)
);

CREATE TABLE app_setting (
    owner_id   TEXT NOT NULL DEFAULT 'local',
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, key)
);
"""


_MIGRATION_004 = """
-- ===========================================================================
-- Phase 2.1: read-path indexes and Universal Research Objects
-- ===========================================================================

-- ``latest_close`` and the market coverage query were scanning the whole bar table
-- once per security, dominating company-list and screener latency. These indexes
-- make the newest-revision lookup and per-security coverage indexed.
CREATE INDEX idx_bar_latest_v4
    ON bar (security_id, mic, interval, ts_utc DESC, revision_seq DESC);
CREATE INDEX idx_bar_security_v4
    ON bar (security_id, mic, ts_utc);
CREATE INDEX idx_evidence_entity_v4
    ON evidence (entity_id, concept, period_end);

-- Research objects are declarative contracts (dataset/model/experiment/strategy/
-- application). They never execute code and never create evidence; the object
-- document is validated by ``atlas.research.objects`` before it is stored.
CREATE TABLE research_object (
    object_id      TEXT PRIMARY KEY,
    owner_id       TEXT NOT NULL DEFAULT 'local',
    kind           TEXT NOT NULL,
    name           TEXT NOT NULL COLLATE NOCASE,
    version        TEXT NOT NULL,
    status         TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    document_json  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE (owner_id, kind, name, version)
);
CREATE INDEX idx_research_object_kind ON research_object (kind, status);

-- Evidence links are real foreign keys so a research object cannot cite a
-- nonexistent evidence id. The reverse index (computation_input) remains the
-- authority for "what depends on this evidence".
CREATE TABLE research_object_evidence (
    object_id   TEXT NOT NULL REFERENCES research_object(object_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
    role        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (object_id, evidence_id, role)
);
CREATE INDEX idx_research_object_evidence ON research_object_evidence (evidence_id);
"""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="phase1_foundation", sql=_MIGRATION_001),
    Migration(version=2, name="phase1_1_history_and_dependencies", sql=_MIGRATION_002),
    Migration(version=3, name="phase2_terminal_user_data", sql=_MIGRATION_003),
    Migration(version=4, name="phase2_1_indexes_and_research_objects", sql=_MIGRATION_004),
)

LATEST_VERSION = max(m.version for m in MIGRATIONS)


def migration_by_version(version: int) -> Migration:
    for migration in MIGRATIONS:
        if migration.version == version:
            return migration
    raise MigrationError("unknown migration version", version=version)


def validate_migration_chain() -> None:
    """Migrations must start at 1 and be strictly sequential."""
    versions = [m.version for m in MIGRATIONS]
    if versions != list(range(1, len(versions) + 1)):  # pragma: no cover - build guard
        raise MigrationError("migration chain is not sequential", versions=versions)
