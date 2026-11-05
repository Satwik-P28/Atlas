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


_MIGRATION_005 = """
-- ===========================================================================
-- Phase 3: materialized financial metrics, compiled model runs, node cache
-- ===========================================================================

-- A snapshot is keyed by the exact information instant and temporal mode, so a value
-- computed from today's disclosures can never answer an earlier as-of query. The
-- generation token covers the issuer's evidence and relevant market observations; a
-- changed token makes the row unusable and it is recomputed.
CREATE TABLE metric_snapshot (
    issuer_id      TEXT NOT NULL REFERENCES issuer(issuer_id),
    as_of          TEXT NOT NULL,
    mode           TEXT NOT NULL,
    model_version  TEXT NOT NULL,
    generation     TEXT NOT NULL,
    period_end     TEXT,
    payload_json   TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (issuer_id, as_of, mode, model_version)
);
CREATE INDEX idx_metric_snapshot_issuer ON metric_snapshot (issuer_id, as_of);

-- Every execution is reproducible from its canonical spec, inputs, compiler/operator
-- versions and information cutoff. Results are never written into evidence.
CREATE TABLE model_run (
    run_id          TEXT PRIMARY KEY,
    model_name      TEXT NOT NULL,
    model_version   TEXT NOT NULL,
    fingerprint     TEXT NOT NULL,
    as_of           TEXT,
    mode            TEXT,
    inputs_json     TEXT NOT NULL,
    result_json     TEXT NOT NULL,
    trace_json      TEXT NOT NULL,
    status          TEXT NOT NULL,
    duration_ms     REAL NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_model_run_fingerprint ON model_run (fingerprint, created_at);

-- Node results are cached only under a key that includes the model fingerprint, node
-- identity, operator version and canonical input values. Changing one input therefore
-- recomputes only its dependent subgraph.
CREATE TABLE model_node_cache (
    cache_key       TEXT PRIMARY KEY,
    fingerprint     TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    operator_key    TEXT NOT NULL,
    operator_version TEXT NOT NULL,
    value_json      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_hit_at     TEXT,
    hits            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_model_node_cache_fingerprint ON model_node_cache (fingerprint, node_id);
"""


_MIGRATION_006 = """
-- ===========================================================================
-- Phase 4: source archives, feature snapshots and quantitative runs
-- ===========================================================================

-- A source archive stores the exact bytes Atlas retrieved so a numerical result can
-- later be checked against source content even if a provider withdraws it. Rights are
-- part of the archive: the presence of bytes does not imply permission to redistribute.
CREATE TABLE source_archive (
    archive_id       TEXT PRIMARY KEY,
    source_id        TEXT NOT NULL REFERENCES source(source_id),
    resource_id      TEXT NOT NULL,
    sha256           TEXT NOT NULL UNIQUE,
    content          BLOB NOT NULL,
    media_type       TEXT NOT NULL,
    retrieved_at     TEXT NOT NULL,
    published_at     TEXT,
    rights           TEXT NOT NULL,
    retention_policy TEXT NOT NULL,
    schema_version   TEXT,
    parser_version   TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX idx_source_archive_resource ON source_archive (source_id, resource_id);

CREATE TABLE source_archive_link (
    archive_id  TEXT NOT NULL REFERENCES source_archive(archive_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
    PRIMARY KEY (archive_id, evidence_id)
);
CREATE INDEX idx_source_archive_link_evidence ON source_archive_link (evidence_id);

-- Cached point-in-time feature series. Generation is supplied by the caller and must
-- incorporate the bar/evidence revisions that influenced the values.
CREATE TABLE feature_snapshot (
    feature_key   TEXT NOT NULL,
    security_id   TEXT NOT NULL REFERENCES security(security_id),
    as_of         TEXT NOT NULL,
    generation    TEXT NOT NULL,
    values_json   TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (feature_key, security_id, as_of)
);
CREATE INDEX idx_feature_snapshot_security ON feature_snapshot (security_id, as_of);

-- A quantitative run is the durable Time Capsule record. It references the strategy
-- object and, when persisted, the experiment object that describes the research intent.
CREATE TABLE quant_run (
    run_id               TEXT PRIMARY KEY,
    strategy_object_id   TEXT REFERENCES research_object(object_id),
    strategy_fingerprint TEXT NOT NULL,
    experiment_object_id TEXT REFERENCES research_object(object_id),
    as_of                TEXT NOT NULL,
    mode                 TEXT NOT NULL,
    start_date           TEXT,
    end_date             TEXT,
    universe_json        TEXT NOT NULL,
    config_json          TEXT NOT NULL,
    result_json          TEXT NOT NULL,
    reconciliation_json  TEXT NOT NULL,
    metrics_json         TEXT NOT NULL,
    status               TEXT NOT NULL,
    duration_ms          REAL NOT NULL,
    created_at           TEXT NOT NULL
);
CREATE INDEX idx_quant_run_strategy ON quant_run (strategy_object_id, created_at);
CREATE INDEX idx_quant_run_fingerprint ON quant_run (strategy_fingerprint, created_at);
"""


_MIGRATION_007 = """
-- ===========================================================================
-- Phase 5: institutional pricing, risk and walk-forward research
-- ===========================================================================

CREATE TABLE institutional_run (
    run_id       TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    as_of        TEXT NOT NULL,
    data_class   TEXT NOT NULL,
    input_json   TEXT NOT NULL,
    result_json  TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    status       TEXT NOT NULL,
    duration_ms  REAL NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_institutional_run_kind ON institutional_run (kind, created_at);
CREATE INDEX idx_institutional_run_fingerprint ON institutional_run (fingerprint);

-- Every candidate evaluated by walk-forward is retained, including candidates that lose.
CREATE TABLE validation_attempt (
    attempt_id        TEXT PRIMARY KEY,
    validation_run_id TEXT NOT NULL REFERENCES institutional_run(run_id) ON DELETE CASCADE,
    fold              INTEGER NOT NULL,
    stage             TEXT NOT NULL,
    family            TEXT NOT NULL,
    lookback          INTEGER NOT NULL,
    selected          INTEGER NOT NULL DEFAULT 0,
    metrics_json      TEXT NOT NULL,
    created_at        TEXT NOT NULL
);
CREATE INDEX idx_validation_attempt_run ON validation_attempt (validation_run_id, fold, stage);
"""


_MIGRATION_008 = """
-- ===========================================================================
-- Phase 6: learning datasets, calibrated forecasts and scientific memory
-- ===========================================================================

-- A learning run is the durable record of a chronological experiment. The raw
-- result is retained even when the hypothesis loses; selection and audit evidence
-- live beside it rather than being reconstructed from a chart.
CREATE TABLE learning_run (
    run_id               TEXT PRIMARY KEY,
    kind                 TEXT NOT NULL,
    dataset_id           TEXT NOT NULL,
    source_id            TEXT,
    target               TEXT NOT NULL,
    data_class           TEXT NOT NULL,
    as_of                TEXT NOT NULL,
    start_date           TEXT,
    end_date             TEXT,
    spec_json            TEXT NOT NULL,
    result_json          TEXT NOT NULL,
    fingerprint          TEXT NOT NULL,
    model_object_id      TEXT REFERENCES research_object(object_id),
    experiment_object_id TEXT REFERENCES research_object(object_id),
    status               TEXT NOT NULL,
    duration_ms          REAL NOT NULL,
    created_at           TEXT NOT NULL
);
CREATE INDEX idx_learning_run_dataset ON learning_run (dataset_id, created_at);
CREATE INDEX idx_learning_run_target ON learning_run (target, created_at);
CREATE INDEX idx_learning_run_fingerprint ON learning_run (fingerprint);

CREATE TABLE learning_attempt (
    attempt_id   TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES learning_run(run_id) ON DELETE CASCADE,
    stage        TEXT NOT NULL,
    model_key    TEXT NOT NULL,
    rank         INTEGER NOT NULL,
    selected     INTEGER NOT NULL DEFAULT 0,
    metrics_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_learning_attempt_run ON learning_attempt (run_id, stage, rank);

-- Model artifacts are immutable JSON. A retrain creates a new row and a new
-- research-object version; no row is updated in place.
CREATE TABLE learning_model (
    model_id          TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL REFERENCES learning_run(run_id) ON DELETE CASCADE,
    object_id         TEXT REFERENCES research_object(object_id),
    name              TEXT NOT NULL,
    version           TEXT NOT NULL,
    family            TEXT NOT NULL,
    target            TEXT NOT NULL,
    dataset_id        TEXT NOT NULL,
    data_class        TEXT NOT NULL,
    feature_schema_json TEXT NOT NULL,
    artifact_json     TEXT NOT NULL,
    metadata_json     TEXT NOT NULL,
    fingerprint       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    UNIQUE (name, version)
);
CREATE INDEX idx_learning_model_run ON learning_model (run_id);
CREATE INDEX idx_learning_model_family ON learning_model (family, created_at);

CREATE TABLE learning_forecast (
    forecast_id  TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES learning_run(run_id) ON DELETE CASCADE,
    model_id     TEXT NOT NULL REFERENCES learning_model(model_id) ON DELETE CASCADE,
    security_id  TEXT NOT NULL,
    as_of        TEXT NOT NULL,
    horizon      INTEGER NOT NULL,
    probability  REAL NOT NULL CHECK (probability >= 0 AND probability <= 1),
    lower        REAL,
    upper        REAL,
    outcome      REAL,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_learning_forecast_run ON learning_forecast (run_id, as_of);
CREATE INDEX idx_learning_forecast_model ON learning_forecast (model_id, as_of);
"""


_MIGRATION_009 = """
-- ===========================================================================
-- Phase 7: economic evidence fabric, graph, claims, scenarios and Sentinel
-- ===========================================================================

CREATE TABLE economic_series (
    series_id          TEXT PRIMARY KEY,
    source_id          TEXT NOT NULL REFERENCES source(source_id),
    dataset            TEXT NOT NULL,
    name               TEXT NOT NULL,
    geography_code     TEXT NOT NULL,
    geography_name     TEXT NOT NULL,
    frequency          TEXT NOT NULL,
    unit               TEXT NOT NULL,
    data_class         TEXT NOT NULL,
    rights             TEXT NOT NULL,
    redistribution     TEXT NOT NULL,
    source_url         TEXT,
    vintage_policy     TEXT NOT NULL,
    publication_policy TEXT NOT NULL,
    metadata_json      TEXT NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE INDEX idx_economic_series_source ON economic_series (source_id, dataset);

-- Economic observations share the temporal-evidence discipline of the financial
-- kernel: economic period, retrieval time, publication evidence, revision chain and
-- an explicit availability basis. A current bulk archive is not a historical vintage.
CREATE TABLE economic_observation (
    observation_id        TEXT PRIMARY KEY,
    series_id             TEXT NOT NULL REFERENCES economic_series(series_id),
    source_id             TEXT NOT NULL REFERENCES source(source_id),
    period_start          TEXT NOT NULL,
    period_end            TEXT NOT NULL,
    published_at          TEXT,
    availability_time     TEXT,
    availability_precision TEXT NOT NULL,
    availability_basis    TEXT NOT NULL,
    observed_at           TEXT NOT NULL,
    vintage               TEXT NOT NULL,
    revision_seq          INTEGER NOT NULL DEFAULT 1 CHECK (revision_seq >= 1),
    supersedes            TEXT REFERENCES economic_observation(observation_id),
    value_numeric         REAL NOT NULL,
    unit                  TEXT NOT NULL,
    quality               TEXT NOT NULL,
    data_class            TEXT NOT NULL,
    raw_ref               TEXT,
    content_hash          TEXT NOT NULL,
    metadata_json         TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    UNIQUE (series_id, period_start, period_end, vintage, revision_seq),
    CHECK (published_at IS NULL OR published_at >= period_end),
    CHECK (availability_precision IN ('exact','date','unknown'))
);
CREATE INDEX idx_economic_observation_series ON economic_observation (series_id, period_start, revision_seq DESC);
CREATE INDEX idx_economic_observation_time ON economic_observation (availability_time, observed_at);

CREATE TABLE economic_entity (
    entity_id       TEXT PRIMARY KEY,
    entity_type     TEXT NOT NULL,
    name            TEXT NOT NULL,
    canonical_key   TEXT NOT NULL,
    geography_code  TEXT,
    data_class      TEXT NOT NULL,
    status          TEXT NOT NULL,
    source_id       TEXT REFERENCES source(source_id),
    valid_from      TEXT,
    valid_to        TEXT,
    metadata_json   TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (entity_type, canonical_key, valid_from)
);
CREATE INDEX idx_economic_entity_type ON economic_entity (entity_type, name);

CREATE TABLE economic_edge (
    edge_id           TEXT PRIMARY KEY,
    from_entity_id    TEXT NOT NULL REFERENCES economic_entity(entity_id),
    to_entity_id      TEXT NOT NULL REFERENCES economic_entity(entity_id),
    relationship_type TEXT NOT NULL,
    source_id         TEXT NOT NULL REFERENCES source(source_id),
    observation_id    TEXT REFERENCES economic_observation(observation_id),
    claim_id          TEXT,
    valid_from        TEXT,
    valid_to          TEXT,
    confidence        REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    epistemic_status  TEXT NOT NULL,
    geography_code    TEXT,
    metadata_json     TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    CHECK (from_entity_id <> to_entity_id)
);
CREATE INDEX idx_economic_edge_from ON economic_edge (from_entity_id, relationship_type);
CREATE INDEX idx_economic_edge_to ON economic_edge (to_entity_id, relationship_type);

CREATE TABLE economic_event (
    event_id         TEXT PRIMARY KEY,
    event_type       TEXT NOT NULL,
    label            TEXT NOT NULL,
    geography_code   TEXT,
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    observed_at      TEXT NOT NULL,
    published_at     TEXT,
    status           TEXT NOT NULL,
    data_class       TEXT NOT NULL,
    source_id        TEXT NOT NULL REFERENCES source(source_id),
    metadata_json    TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX idx_economic_event_time ON economic_event (started_at, event_type);

CREATE TABLE economic_claim (
    claim_id          TEXT PRIMARY KEY,
    subject_key       TEXT NOT NULL,
    predicate         TEXT NOT NULL,
    value_numeric     REAL,
    value_text        TEXT,
    unit              TEXT,
    observed_at       TEXT NOT NULL,
    claimed_at        TEXT NOT NULL,
    source_id         TEXT NOT NULL REFERENCES source(source_id),
    observation_id    TEXT REFERENCES economic_observation(observation_id),
    epistemic_status  TEXT NOT NULL,
    causal_status     TEXT NOT NULL,
    review_status     TEXT NOT NULL,
    supersedes        TEXT REFERENCES economic_claim(claim_id),
    metadata_json     TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    CHECK (epistemic_status IN ('observed','inferred','hypothesized','estimated_causal_effect','counterfactual','unresolved')),
    CHECK (causal_status IN ('not_applicable','association','identified','not_identified'))
);
CREATE INDEX idx_economic_claim_subject ON economic_claim (subject_key, claimed_at);
CREATE INDEX idx_economic_claim_status ON economic_claim (epistemic_status, causal_status);

CREATE TABLE economic_conflict (
    conflict_id      TEXT PRIMARY KEY,
    subject_key      TEXT NOT NULL,
    claim_ids_json   TEXT NOT NULL,
    status           TEXT NOT NULL,
    reason           TEXT NOT NULL,
    resolution       TEXT,
    detected_at      TEXT NOT NULL,
    metadata_json    TEXT NOT NULL,
    UNIQUE (subject_key, detected_at)
);
CREATE INDEX idx_economic_conflict_status ON economic_conflict (status, detected_at);

CREATE TABLE economic_analysis (
    run_id              TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,
    as_of               TEXT NOT NULL,
    mode                TEXT NOT NULL,
    data_class          TEXT NOT NULL,
    start_date          TEXT NOT NULL,
    end_date            TEXT NOT NULL,
    spec_json           TEXT NOT NULL,
    result_json         TEXT NOT NULL,
    fingerprint         TEXT NOT NULL,
    model_object_id     TEXT REFERENCES research_object(object_id),
    experiment_object_id TEXT REFERENCES research_object(object_id),
    application_object_id TEXT REFERENCES research_object(object_id),
    status              TEXT NOT NULL,
    stale               INTEGER NOT NULL DEFAULT 0,
    stale_reason        TEXT,
    duration_ms         REAL NOT NULL,
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_economic_analysis_created ON economic_analysis (created_at DESC);
CREATE INDEX idx_economic_analysis_fingerprint ON economic_analysis (fingerprint);

CREATE TABLE economic_scenario (
    scenario_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES economic_analysis(run_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    result_json     TEXT NOT NULL,
    fingerprint     TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_economic_scenario_run ON economic_scenario (run_id, created_at);

CREATE TABLE economic_dependency (
    run_id          TEXT NOT NULL REFERENCES economic_analysis(run_id) ON DELETE CASCADE,
    dependency_type TEXT NOT NULL,
    dependency_id   TEXT NOT NULL,
    role            TEXT NOT NULL,
    stale           INTEGER NOT NULL DEFAULT 0,
    invalidated_at  TEXT,
    reason          TEXT,
    PRIMARY KEY (run_id, dependency_type, dependency_id)
);
CREATE INDEX idx_economic_dependency_target ON economic_dependency (dependency_type, dependency_id);

CREATE TABLE economic_alert (
    alert_id      TEXT PRIMARY KEY,
    alert_type    TEXT NOT NULL,
    severity      TEXT NOT NULL,
    run_id        TEXT REFERENCES economic_analysis(run_id) ON DELETE CASCADE,
    dependency_id TEXT,
    summary       TEXT NOT NULL,
    detail_json   TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE (alert_type, run_id, dependency_id, created_at)
);
CREATE INDEX idx_economic_alert_status ON economic_alert (status, created_at DESC);
"""


_MIGRATION_010 = """
-- ===========================================================================
-- Phase 8: portable application packages, installs, executions and packs
-- ===========================================================================

-- The package bytes are retained so verification is possible after installation and
-- so export reproduces exactly the bytes that were installed. The manifest is stored
-- separately for querying; it is never trusted without revalidation against the blob.
CREATE TABLE application_installation (
    install_id             TEXT PRIMARY KEY,
    application_id         TEXT NOT NULL,
    version                TEXT NOT NULL,
    publisher_id           TEXT NOT NULL,
    package_id             TEXT NOT NULL,
    package_sha256         TEXT NOT NULL UNIQUE,
    package_size           INTEGER NOT NULL CHECK (package_size > 0),
    manifest_json          TEXT NOT NULL,
    application_json       TEXT NOT NULL,
    package_blob           BLOB NOT NULL,
    status                 TEXT NOT NULL CHECK (status IN ('installed','inspect_only','quarantined')),
    reproducibility        TEXT NOT NULL,
    trust_level            TEXT NOT NULL,
    signature_status       TEXT NOT NULL,
    object_id              TEXT REFERENCES research_object(object_id),
    source_installation_id TEXT,
    diagnostics_json       TEXT NOT NULL DEFAULT '[]',
    installed_at           TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    UNIQUE (application_id, version, publisher_id)
);
CREATE INDEX idx_application_installation_app ON application_installation (application_id, version);
CREATE INDEX idx_application_installation_time ON application_installation (installed_at DESC);

-- Execution history survives uninstall: removing an installed application cannot
-- rewrite the fact that a result was produced. There is intentionally no foreign key.
CREATE TABLE application_execution (
    execution_id TEXT PRIMARY KEY,
    install_id   TEXT NOT NULL,
    status       TEXT NOT NULL,
    result_json  TEXT NOT NULL,
    duration_ms  REAL NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_application_execution_install ON application_execution (install_id, created_at DESC);

CREATE TABLE domain_pack_installation (
    pack_id         TEXT NOT NULL,
    version         TEXT NOT NULL,
    publisher_id    TEXT NOT NULL,
    manifest_json   TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    applications_json TEXT NOT NULL DEFAULT '[]',
    installed_at    TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (pack_id, version, publisher_id)
);
CREATE INDEX idx_domain_pack_installation_time ON domain_pack_installation (installed_at DESC);
"""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="phase1_foundation", sql=_MIGRATION_001),
    Migration(version=2, name="phase1_1_history_and_dependencies", sql=_MIGRATION_002),
    Migration(version=3, name="phase2_terminal_user_data", sql=_MIGRATION_003),
    Migration(version=4, name="phase2_1_indexes_and_research_objects", sql=_MIGRATION_004),
    Migration(version=5, name="phase3_metrics_and_model_runtime", sql=_MIGRATION_005),
    Migration(version=6, name="phase4_source_archive_and_quant_lab", sql=_MIGRATION_006),
    Migration(version=7, name="phase5_institutional_research", sql=_MIGRATION_007),
    Migration(version=8, name="phase6_learning_runtime", sql=_MIGRATION_008),
    Migration(version=9, name="phase7_economic_intelligence", sql=_MIGRATION_009),
    Migration(version=10, name="phase8_portable_applications", sql=_MIGRATION_010),
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
