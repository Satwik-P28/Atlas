/** Shapes returned by the Atlas terminal API. Kept explicit so a contract change is a
 * compile error rather than a blank cell. Fields optional here are optional in the
 * documented JSON (e.g. a missing metric is omitted, never zeroed). */

export type Mode = 'standard' | 'advanced'
export type Theme = 'dark' | 'light'
export type AsOfMode = 'public_available' | 'atlas_ingested'
export type PriceView = 'raw' | 'split' | 'total_return'

export interface Ticker {
  ticker: string | null
  mic: string | null
  valid_from?: string | null
  status?: string | null
  confidence?: number | null
}

export interface SecuritySummary {
  security_id: string
  issuer_id: string
  class_designation: string
  security_type: string
  currency: string | null
  status: string | null
  tickers: Ticker[]
  mic: string | null
  last_close: string | null
  last_bar_date: string | null
  sessions: number
  data_status: string
}

export interface CompanySummary {
  issuer_id: string
  cik: string | null
  legal_name: string
  entity_type?: string | null
  sic?: string | null
  fiscal_year_end?: string | null
  domicile_country?: string | null
  securities: SecuritySummary[]
  evidence_count: number
  filing_count: number
}

export interface CompanyDetail extends CompanySummary {
  availability: { exact: number; date: number; unknown: number }
  latest_filing: {
    accession_number: string
    form_type: string
    filed_date: string
    acceptance_datetime: string | null
  } | null
  warnings: string[]
  schema: string
}

export interface StatementCell {
  value: string | null
  unit: string
  missing: boolean
  evidence_id?: string
  flags?: string[]
  revision_kind?: string
  revision_count?: number
  derivation_kind?: string
  derivation_rule?: string | null
  availability_time?: string | null
  availability_precision?: string
  quality?: string
  accession_number?: string | null
  form_type?: string | null
}

export interface StatementColumn {
  period_end: string
  period_start: string | null
  fiscal_year: number | null
  fiscal_period: string | null
  revision_kind: string | null
  accession_number: string | null
}

export interface StatementRow {
  concept: string
  label: string
  unit: string
  cells: StatementCell[]
}

export interface StatementsResponse {
  issuer: { issuer_id: string; legal_name: string; cik: string | null }
  statement: 'income' | 'balance' | 'cashflow'
  period: 'FY' | 'Q'
  as_of: string
  mode: AsOfMode
  policy: string
  completeness: string
  excluded_not_yet_available: number
  excluded_unknown_availability: number
  contradictions: Array<{ concept: string; values: string[]; evidence_ids: string[]; selected: string; note: string }>
  notes: string[]
  columns: StatementColumn[]
  rows: StatementRow[]
  units_note: string
  schema: string
}

export interface Metric {
  key: string
  label: string
  value: number
  text: string
  unit: string
  kind: string
  formula: string | null
  period_end: string | null
  price_as_of?: string | null
  evidence_ids: string[]
  note?: string | null
  inputs?: string[]
  comparison_period_end?: string | null
}

export interface MetricsResponse {
  issuer: { issuer_id: string; legal_name: string }
  as_of: string
  mode: AsOfMode
  policy: string
  period_end: string | null
  comparison_period_end: string | null
  price_as_of: string | null
  price: number | null
  price_source: string | null
  completeness: string
  metrics: Record<string, Metric>
  missing: string[]
  notes: string[]
  schema: string
}

export interface BarPoint {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number | null
  split_factor?: number
}

export interface IndicatorSeries {
  name: string
  role: 'line' | 'band' | 'histogram'
  points: Array<{ time: string; value: number }>
  observations: number
}

export interface IndicatorResult {
  key: string
  label: string
  version: string
  calculation_id: string
  params: Record<string, number>
  pane: 'overlay' | 'separate'
  formula: string
  series: IndicatorSeries[]
  warmup: number
  insufficient_data: boolean
  warnings: string[]
}

export interface MarketResponse {
  security: {
    security_id: string
    issuer_id: string
    legal_name: string | null
    class_designation: string | null
    ticker: string | null
  }
  mic: string
  view: PriceView
  range: { start: string; end: string }
  requested_range: string
  range_note: string | null
  as_of: string | null
  coverage: { first: string | null; last: string | null; sessions: number; rows: number }
  bars: BarPoint[]
  index: Array<{ time: string; value: number }>
  adjustment_status: string
  price_basis_note: string
  actions: Array<Record<string, unknown> & { ex_date?: string | null; action_type?: string; ratio_from?: string; ratio_to?: string }>
  actions_applied: Array<Record<string, unknown>>
  actions_withheld: Array<Record<string, unknown>>
  indicators: IndicatorResult[]
  indicator_signature: string | null
  sources: SourceInfo[]
  data_status: string
  last_bar: { date: string; close: number; observed_at?: string | null; source_id?: string | null } | null
  warnings: string[]
  truncated: boolean
  schema: string
}

export interface SourceInfo {
  source_id: string
  name: string
  kind: string
  licence: string | null
  redistribution: string
}

export interface FilingItem {
  filing_id: string
  accession_number: string
  form_type: string
  form_label: string
  filed_date: string
  acceptance_datetime: string | null
  period_of_report: string | null
  is_amendment: boolean
  amends_accession: string | null
  primary_document: string | null
  source_url: string | null
  source_id: string
}

export interface FilingsResponse {
  issuer: { issuer_id: string; legal_name: string }
  total: number
  limit: number
  offset: number
  items: FilingItem[]
  notes: string[]
}

export interface EventItem {
  kind: 'filing' | 'corporate_action'
  date: string
  timestamp: string | null
  title: string
  detail: string
  reference: string
  amendment?: boolean
  source_id?: string
  security_id?: string
}

export interface EventsResponse {
  issuer: { issuer_id: string; legal_name: string }
  items: EventItem[]
  counts: { filings: number; corporate_actions: number }
}

export interface XrayResponse {
  record: Record<string, unknown> & {
    evidence_id?: string
    concept?: string
    value?: string
    unit?: string
    period_start?: string | null
    period_end?: string | null
    availability_time?: string | null
    availability_precision?: string
    observed_at?: string
    derivation_kind?: string
    derivation_rule?: string | null
    quality?: string
    verification?: string
    source_concept?: string | null
    accession_number?: string | null
    form_type?: string | null
  }
  source: Record<string, unknown> & { source_id?: string; name?: string; licence?: string | null; kind?: string }
  raw_document: Record<string, unknown> & { url?: string; content_hash?: string; retrieved_at?: string }
  filing: Record<string, unknown> | null
  transformation: Record<string, unknown> | null
  revision_chain: Array<Record<string, unknown>>
  derived_inputs: Array<Record<string, unknown>>
  limitations: string[]
  narrative: string[]
  terminal: { policy: string; schema: string; holds: string }
}

export interface ScreenerMetric {
  key: string
  label: string
  unit: string
  formula: string | null
  kind: string
}

export interface ScreenerRow {
  issuer_id: string
  legal_name: string
  ticker: string | null
  security_id: string | null
  period_end: string | null
  price_as_of: string | null
  metrics: Record<string, { value: number | null; text: string; unit: string; formula: string | null; evidence_ids: string[] }>
  missing: string[]
}

export interface ScreenerResponse {
  matched: number
  returned: number
  rows: ScreenerRow[]
  universe: {
    issuers_in_database: number
    evaluated: number
    excluded_for_missing_inputs: number
    note: string
  }
  filters: Array<{ metric: string; op: string; value: number; value2?: number }>
  match: 'AND' | 'OR'
  as_of: string
  mode: AsOfMode
  covered_metrics: string[]
  skipped: Array<{ issuer_id: string; legal_name: string; missing: string[] }>
  notes: string[]
}

export interface WatchlistItem {
  security_id: string
  position: number
  added_at: string
  ticker: string | null
  mic: string | null
  legal_name: string | null
  class_designation: string
  security_type: string
  issuer_id: string
}

export interface Watchlist {
  watchlist_id: string
  name: string
  notes: string | null
  created_at: string
  updated_at: string
  items: WatchlistItem[]
}

export interface PanelConfig {
  id: string
  type: string
  title: string
  span: number
  config: Record<string, unknown>
  /** Only present in `atlas.workspace.v2`: which linked instrument group the panel follows. */
  link_group?: 'A' | 'B' | 'C' | 'D' | null
  issuer_id?: string
  security_id?: string
  evidence_id?: string
  watchlist_id?: string
}

export interface WorkspaceDocument {
  name: string
  mode: Mode
  columns: number
  description?: string | null
  panels: PanelConfig[]
  schema?: string
  /** `atlas.workspace.v2` split/tab tree; validated by the same grammar as the server. */
  layout?: unknown
}

export interface Workspace {
  workspace_id: string
  name: string
  mode: Mode
  schema: string
  fingerprint: string
  created_at: string
  updated_at: string
  document: WorkspaceDocument
}

export interface MarketOverviewItem {
  security_id: string
  issuer_id: string
  legal_name: string | null
  ticker: string | null
  mic: string
  last_close: number
  last_bar_date: string
  change_1d: number | null
  change_1y: number | null
  volume: number | null
  sparkline: number[]
  sessions: number
  data_status: string
  currency: string | null
}

export interface MarketOverview {
  items: MarketOverviewItem[]
  count: number
  as_of: string
  data_status: string
  sources: SourceInfo[]
  notes: string[]
}

export interface FinancialHistory {
  issuer: { issuer_id: string; legal_name: string; cik?: string | null }
  as_of: string
  mode: AsOfMode
  periods: string[]
  concepts: Array<{
    concept: string
    label: string
    unit: string
    points: Array<{
      period_end: string
      value: number | null
      text: string | null
      unit: string
      evidence_id: string
      revision_kind: string
    }>
  }>
  completeness: string
  notes: string[]
}

export interface PeerRow {
  issuer_id: string
  legal_name: string
  ticker: string | null
  is_target: boolean
  period_end: string | null
  data_status: string | null
  metrics: Record<string, { value: number | null; text: string | null; unit: string }>
}

export interface PeersResponse {
  issuer: { issuer_id: string; legal_name: string }
  as_of: string
  mode: AsOfMode
  rows: PeerRow[]
  labels: Record<string, string>
  medians: Record<string, number>
  universe: { issuers: number; note: string }
  notes: string[]
}

export interface RevisionsResponse {
  issuer: { issuer_id: string; legal_name: string }
  revisions: Array<{
    evidence_id: string
    concept: string
    period_end: string | null
    revision_kind: string
    supersedes: string | null
    availability_time: string | null
    value: string | number | null
    unit: string
    accession_number: string | null
    form_type: string | null
  }>
  amended_filings: Array<{
    accession_number: string
    form_type: string
    filed_date: string
    period_of_report: string | null
    amends_accession: string | null
  }>
  counts: { evidence_revisions: number; amended_filings: number }
  notes: string[]
}

export interface ValidationResponse {
  issuer: { issuer_id: string; legal_name: string }
  as_of: string
  mode: AsOfMode
  security_id: string | null
  checks: Array<{
    name: string
    expected: string
    actual: string
    difference: string | null
    tolerance: string
    passed: boolean
    evidence_ids: string[]
    note: string | null
  }>
  passed: number
  failed: number
  total: number
  status: 'verified' | 'failed' | 'insufficient_data'
  tolerances: Record<string, string>
  notes: string[]
}

export type IndicatorConfig = { key: string; params?: Record<string, number> }

/* ---------------------------------------------------------------- price movement */
export type PriceExplanationBasis = 'price' | 'split_adjusted' | 'total_return'
export type PriceExplanationMode = 'historical_reconstruction' | 'retrospective_investigation'

export interface PriceExplanationRequest {
  start_session: string
  end_session: string
  price_basis: PriceExplanationBasis
  mode: PriceExplanationMode
  information_cutoff?: string | null
  benchmark_security_id?: string | null
  estimation_sessions?: number
}

export interface PriceExplanationWarning {
  code: string
  message: string
  context?: Record<string, unknown>
}

export interface PriceExplanationEvent {
  event_id: string
  kind: string
  title: string
  date: string
  availability_time: string | null
  availability_precision?: string | null
  form_type?: string
  form_label?: string
  period_of_report?: string | null
  accession_number?: string | null
  is_amendment?: boolean
  amends_accession?: string | null
  action_type?: string
  ratio_from?: string | null
  ratio_to?: string | null
  cash_amount?: string | null
  status?: string
  source_id?: string | null
  relation: 'in_window' | 'after_window' | 'subsequent'
  known_at_range_end?: boolean
  epistemic_status: string
}

export interface PriceExplanationHypothesis {
  hypothesis_id: string
  rank: number
  statement: string
  epistemic_status: string
  causal_status: string
  relevance: {
    tier: number
    basis: string
    supporting_evidence: string[]
    contradicting_evidence: string[]
    inputs: Record<string, unknown>
  }
  limitations: string[]
}

export interface PriceExplanation {
  schema: string
  engine: { name: string; version: string }
  request: Record<string, unknown>
  selection: {
    security_id: string
    issuer_id: string
    legal_name: string | null
    ticker: string | null
    mic: string
    timeframe: string
    timezone: string
    requested_start: string
    requested_end: string
    start_session: string
    end_session: string
    sessions: number
    series: Record<string, unknown>
    start_observation: Record<string, unknown>
    end_observation: Record<string, unknown>
  }
  price_statistics: {
    requested_basis: PriceExplanationBasis
    basis_label: string
    currency: string
    start_session: string
    end_session: string
    sessions: number
    calendar_days: number
    start_price: number
    end_price: number
    absolute_change: number
    interval_return: number
    daily_volatility: number | null
    annualized_volatility: number | null
    max_drawdown: number
    overnight_compounded: number | null
    intraday_compounded: number | null
    gap_sessions: number
    gap_note: string
    volume: {
      sessions_with_volume: number
      total: number | null
      average: number | null
      trailing_median: number | null
      average_to_trailing_median: number | null
      context_sessions: number
      note: string
    }
    basis_reconciliation: {
      raw: number
      split_adjusted: number
      total_return: number
      splits_in_window: number
      dividends_in_window: number
      note: string
    }
    start_observation_id: string
    end_observation_id: string
  }
  benchmark: {
    status: string
    security_id: string | null
    ticker?: string | null
    return?: number
    excess_return_arithmetic?: number
    excess_note?: string
    reason: string | null
  }
  peers: Array<{
    security_id: string
    ticker?: string | null
    status: string
    reason: string | null
    comparable: boolean
    currency?: string
    sessions?: number
    return?: number | null
    source_id?: string | null
  }>
  market_model: {
    status: string
    reason?: string | null
    beta?: number
    r_squared?: number | null
    alpha_daily?: number
    market_component_of_return?: number
    residual_return_arithmetic?: number
    estimation?: {
      sessions: number
      first_session: string | null
      last_session: string | null
      window_rule: string
      aligned_available: number
    }
    applicability?: string[]
  }
  events: {
    items: PriceExplanationEvent[]
    in_window_count: number
    subsequent_count: number
    coverage: Record<string, unknown>
  }
  observations: Array<{
    observation_id: string
    statement: string
    value: number | string
    unit: string
    evidence: string[]
    derivation: string
  }>
  hypotheses: PriceExplanationHypothesis[]
  revision_check: {
    subsequent_revisions: number
    amending_filings: number
    corrected_corporate_actions: number
    status: string
  }
  rights: {
    export_allowed: boolean
    sources: Array<{ source_id: string; name: string; licence: string | null; redistribution: string; kind: string }>
    restricted_sources: string[]
  }
  warnings: PriceExplanationWarning[]
  refusals: Array<Record<string, unknown>>
  reproducibility: { hash_algorithm: string; hash: string; components: Record<string, unknown>; note: string }
  limitations: string[]
}
