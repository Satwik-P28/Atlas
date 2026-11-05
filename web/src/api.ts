import type {
  AsOfMode,
  CompanyDetail,
  CompanySummary,
  EventsResponse,
  FilingsResponse,
  FinancialHistory,
  IndicatorConfig,
  IndicatorResult,
  MarketOverview,
  MarketResponse,
  MetricsResponse,
  Mode,
  PeersResponse,
  PriceView,
  RevisionsResponse,
  ScreenerMetric,
  ScreenerResponse,
  StatementsResponse,
  ValidationResponse,
  Watchlist,
  Workspace,
  WorkspaceDocument,
  XrayResponse,
} from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  status: number
  code: string
  context: unknown

  constructor(status: number, code: string, message: string, context: unknown = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.context = context
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (response.status === 204) return undefined as T
  const text = await response.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = null
  }
  if (!response.ok) {
    const error = (body as { error?: { code?: string; message?: string; context?: unknown } } | null)?.error
    throw new ApiError(
      response.status,
      error?.code ?? 'http_error',
      error?.message ?? `Request failed (${response.status})`,
      error?.context ?? {},
    )
  }
  return body as T
}

const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

const enc = encodeURIComponent

export const api = {
  health: () => request<Record<string, unknown>>('/api/health'),
  schema: () => request<Record<string, unknown>>('/api/schema'),
  companies: (q?: string) => request<{ items: CompanySummary[]; count: number }>(`/api/companies${qs({ q })}`),
  company: (identifier: string) => request<CompanyDetail>(`/api/companies/${enc(identifier)}`),
  search: (q: string) =>
    request<{ items: Array<{ type: string; issuer_id: string; label: string; cik: string | null; tickers: string[]; security_id: string | null }> }>(
      `/api/search${qs({ q })}`,
    ),
  statements: (
    identifier: string,
    options: { statement: string; period: 'FY' | 'Q'; asOf?: string | null; mode: AsOfMode; limit?: number },
  ) =>
    request<StatementsResponse>(
      `/api/companies/${enc(identifier)}/statements${qs({
        statement: options.statement,
        period: options.period,
        as_of: options.asOf,
        mode: options.mode,
        limit: options.limit,
      })}`,
    ),
  metrics: (identifier: string, options: { asOf?: string | null; mode: AsOfMode }) =>
    request<MetricsResponse>(`/api/companies/${enc(identifier)}/metrics${qs({ as_of: options.asOf, mode: options.mode })}`),
  filings: (identifier: string, options: { limit?: number; offset?: number; forms?: string[] } = {}) =>
    request<FilingsResponse>(
      `/api/companies/${enc(identifier)}/filings${qs({
        limit: options.limit,
        offset: options.offset,
        forms: options.forms?.join(','),
      })}`,
    ),
  events: (identifier: string, limit = 40) =>
    request<EventsResponse>(`/api/companies/${enc(identifier)}/events${qs({ limit })}`),
  markets: () => request<MarketOverview>('/api/markets/overview'),
  market: (
    securityId: string,
    options: {
      range: string
      view: PriceView
      indicators: IndicatorConfig[]
      asOf?: string | null
      chartType?: string
    },
  ) =>
    request<MarketResponse>(`/api/securities/${enc(securityId)}/market`, {
      method: 'POST',
      body: JSON.stringify({
        range: options.range,
        view: options.view,
        indicators: options.indicators,
        as_of: options.asOf ?? null,
      }),
    }),
  history: (identifier: string, options: { asOf?: string | null; mode: AsOfMode; limit?: number; concepts?: string[] }) =>
    request<FinancialHistory>(
      `/api/companies/${enc(identifier)}/history${qs({
        as_of: options.asOf,
        mode: options.mode,
        limit: options.limit,
        concepts: options.concepts?.join(','),
      })}`,
    ),
  peers: (identifier: string, options: { asOf?: string | null; mode: AsOfMode }) =>
    request<PeersResponse>(`/api/companies/${enc(identifier)}/peers${qs({ as_of: options.asOf, mode: options.mode })}`),
  revisions: (identifier: string, limit = 50) =>
    request<RevisionsResponse>(`/api/companies/${enc(identifier)}/revisions${qs({ limit })}`),
  validate: (identifier: string, options: { asOf?: string | null; mode: AsOfMode }) =>
    request<ValidationResponse>(`/api/research/validation/${enc(identifier)}${qs({ as_of: options.asOf, mode: options.mode })}`),
  xray: (evidenceId: string) => request<XrayResponse>(`/api/evidence/${enc(evidenceId)}`),
  indicators: () => request<{ items: Array<Record<string, unknown>> }>('/api/indicators'),
  screenerMetrics: () => request<{ items: ScreenerMetric[] }>('/api/screeners/metrics'),
  screen: (body: {
    filters: Array<{ metric: string; op: string; value: number; value2?: number }>
    match: 'AND' | 'OR'
    sort?: { metric: string; direction: 'asc' | 'desc' } | null
    limit?: number
    as_of?: string | null
    mode?: AsOfMode
  }) => request<ScreenerResponse>('/api/screeners/run', { method: 'POST', body: JSON.stringify(body) }),
  watchlists: () => request<{ items: Watchlist[] }>('/api/watchlists'),
  createWatchlist: (body: { name: string; notes?: string | null; security_ids?: string[] }) =>
    request<Watchlist>('/api/watchlists', { method: 'POST', body: JSON.stringify(body) }),
  renameWatchlist: (id: string, body: { name?: string; notes?: string | null }) =>
    request<Watchlist>(`/api/watchlists/${enc(id)}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteWatchlist: (id: string) => request<void>(`/api/watchlists/${enc(id)}`, { method: 'DELETE' }),
  addWatchlistItem: (id: string, securityId: string) =>
    request<Watchlist>(`/api/watchlists/${enc(id)}/items`, {
      method: 'POST',
      body: JSON.stringify({ security_id: securityId }),
    }),
  removeWatchlistItem: (id: string, securityId: string) =>
    request<Watchlist>(`/api/watchlists/${enc(id)}/items/${enc(securityId)}`, { method: 'DELETE' }),
  reorderWatchlist: (id: string, securityIds: string[]) =>
    request<Watchlist>(`/api/watchlists/${enc(id)}/order`, {
      method: 'PUT',
      body: JSON.stringify({ security_ids: securityIds }),
    }),
  presets: (issuerId?: string, securityId?: string) =>
    request<{ items: WorkspaceDocument[]; resolved: boolean; placeholders: string[] }>(
      `/api/workspaces/presets${qs({ issuer: issuerId, security: securityId })}`,
    ),
  workspaces: () => request<{ items: Workspace[] }>('/api/workspaces'),
  workspace: (id: string) => request<Workspace>(`/api/workspaces/${enc(id)}`),
  createWorkspace: (document: WorkspaceDocument) =>
    request<Workspace>('/api/workspaces', { method: 'POST', body: JSON.stringify(document) }),
  updateWorkspace: (id: string, document: WorkspaceDocument) =>
    request<Workspace>(`/api/workspaces/${enc(id)}`, { method: 'PUT', body: JSON.stringify(document) }),
  deleteWorkspace: (id: string) => request<void>(`/api/workspaces/${enc(id)}`, { method: 'DELETE' }),
  settings: () => request<{ values: Record<string, unknown> }>('/api/settings'),
  setSetting: (key: string, value: unknown) =>
    request<{ values: Record<string, unknown> }>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify({ key, value }),
    }),
  previewIndicator: (body: {
    security_id: string
    range: string
    view: PriceView
    indicators: IndicatorConfig[]
  }) =>
    request<{ indicators: IndicatorResult[]; signature: string; bars: number }>('/api/indicators/preview', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  modelCompile: (spec: unknown) =>
    request<Record<string, unknown>>('/api/models/compile', {
      method: 'POST',
      body: JSON.stringify({ spec }),
    }),
  modelRun: (spec: unknown, inputs: Record<string, unknown>, persist = true) =>
    request<Record<string, any>>('/api/models/run', {
      method: 'POST',
      body: JSON.stringify({ spec, inputs, persist }),
    }),
  valuationDefaults: (identifier: string, asOf?: string | null, mode?: AsOfMode) =>
    request<Record<string, any>>(
      `/api/valuation/defaults/${enc(identifier)}${qs({ as_of: asOf, mode })}`,
    ),
  valuationDcf: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/valuation/dcf', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  valuationReverse: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/valuation/reverse', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  valuationScenarios: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/valuation/scenarios', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  valuationSensitivity: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/valuation/sensitivity', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  researchObjects: (kind?: string) =>
    request<{ items: Array<Record<string, any>>; kinds: string[] }>(
      `/api/research/objects${qs({ kind, limit: 50 })}`,
    ),
  createResearchObject: (document: Record<string, unknown>) =>
    request<Record<string, any>>('/api/research/objects', {
      method: 'POST',
      body: JSON.stringify({ document }),
    }),
  researchObject: (objectId: string) =>
    request<Record<string, any>>(`/api/research/objects/${enc(objectId)}`),
  forkResearchObject: (objectId: string, name: string, version = '1.0.0') =>
    request<Record<string, any>>(`/api/research/objects/${enc(objectId)}/fork`, {
      method: 'POST',
      body: JSON.stringify({ name, version }),
    }),
  compareResearchObjects: (left: string, right: string) =>
    request<Record<string, any>>(`/api/research/compare${qs({ left, right })}`),
  exportResearchObject: (objectId: string) =>
    request<Record<string, any>>(`/api/research/objects/${enc(objectId)}/export`),
  executeResearchObject: (objectId: string, inputs: Record<string, unknown>) =>
    request<Record<string, any>>(`/api/research/objects/${enc(objectId)}/execute`, {
      method: 'POST',
      body: JSON.stringify({ inputs, persist: true }),
    }),
  quantCatalog: () => request<Record<string, any>>('/api/quant/catalog'),
  quantStrategies: () => request<{ items: Array<Record<string, any>>; count: number }>('/api/quant/strategies'),
  quantFeatures: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/quant/features', { method: 'POST', body: JSON.stringify(body) }),
  quantBacktest: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/quant/backtest', { method: 'POST', body: JSON.stringify(body) }),
  quantRuns: () => request<{ items: Array<Record<string, any>>; schema: string }>('/api/quant/runs'),
  quantRun: (runId: string) => request<Record<string, any>>(`/api/quant/runs/${enc(runId)}`),
  quantCapsule: (runId: string) =>
    request<Record<string, any>>(`/api/quant/runs/${enc(runId)}/capsule`),
  quantReplay: (runId: string) =>
    request<Record<string, any>>(`/api/quant/runs/${enc(runId)}/replay`, { method: 'POST' }),
  quantExperiments: () => request<{ items: Array<Record<string, any>>; count: number }>('/api/quant/experiments'),
  archiveSource: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/research/archive', { method: 'POST', body: JSON.stringify(body) }),
  institutionalCatalog: () => request<Record<string, any>>('/api/institutional/catalog'),
  institutionalUniverse: () => request<Record<string, any>>('/api/institutional/universe'),
  institutionalCurve: (date = '2024-06-28') =>
    request<Record<string, any>>(`/api/institutional/curve${qs({ date })}`),
  institutionalBond: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/institutional/bond', { method: 'POST', body: JSON.stringify(body) }),
  institutionalOption: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/institutional/option', { method: 'POST', body: JSON.stringify(body) }),
  institutionalPortfolio: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/institutional/portfolio', { method: 'POST', body: JSON.stringify(body) }),
  institutionalOptimize: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/institutional/optimize', { method: 'POST', body: JSON.stringify(body) }),
  institutionalValidate: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/institutional/validate', { method: 'POST', body: JSON.stringify(body) }),
  institutionalRuns: () => request<Record<string, any>>('/api/institutional/runs'),
  institutionalRun: (runId: string) => request<Record<string, any>>(`/api/institutional/runs/${enc(runId)}`),
  institutionalAttempts: (runId: string) =>
    request<Record<string, any>>(`/api/institutional/runs/${enc(runId)}/attempts`),
  institutionalApplications: () => request<Record<string, any>>('/api/institutional/applications'),
  institutionalApplication: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/institutional/applications', { method: 'POST', body: JSON.stringify(body) }),
  learningCatalog: () => request<Record<string, any>>('/api/learning/catalog'),
  learningDataset: (dataset?: string | null) =>
    request<Record<string, any>>(`/api/learning/dataset${qs({ dataset })}`),
  learningExperiment: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/learning/experiment', { method: 'POST', body: JSON.stringify(body) }),
  learningRuns: () => request<Record<string, any>>('/api/learning/runs'),
  learningRun: (runId: string) => request<Record<string, any>>(`/api/learning/runs/${enc(runId)}`),
  learningForecasts: (runId: string, securityId?: string) =>
    request<Record<string, any>>(`/api/learning/runs/${enc(runId)}/forecasts${qs({ security_id: securityId })}`),
  learningAudit: (runId: string) =>
    request<Record<string, any>>(`/api/learning/runs/${enc(runId)}/audit`),
  learningMonitor: (runId: string) =>
    request<Record<string, any>>(`/api/learning/runs/${enc(runId)}/monitor`),
  learningPortfolio: (runId: string, body: Record<string, unknown>) =>
    request<Record<string, any>>(`/api/learning/runs/${enc(runId)}/portfolio`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  learningModels: () => request<Record<string, any>>('/api/learning/models'),
  learningMemory: (body: Record<string, unknown> = {}) =>
    request<Record<string, any>>('/api/learning/memory', { method: 'POST', body: JSON.stringify(body) }),
  learningDiscovery: (body: Record<string, unknown> = {}) =>
    request<Record<string, any>>('/api/learning/discovery', { method: 'POST', body: JSON.stringify(body) }),
  learningApplication: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/learning/applications', { method: 'POST', body: JSON.stringify(body) }),
  learningApplications: () => request<Record<string, any>>('/api/learning/applications'),
  economicCatalog: () => request<Record<string, any>>('/api/economic/catalog'),
  economicPanel: (asOf?: string | null, mode: AsOfMode = 'public_available') =>
    request<Record<string, any>>(`/api/economic/panel${qs({ as_of: asOf, mode })}`),
  economicGraph: (asOf?: string | null, entityId?: string, depth = 2) =>
    request<Record<string, any>>(`/api/economic/graph${qs({ as_of: asOf, entity_id: entityId, depth })}`),
  economicConflicts: () => request<Record<string, any>>('/api/economic/conflicts'),
  economicRuns: () => request<Record<string, any>>('/api/economic/runs'),
  economicRun: (runId: string) => request<Record<string, any>>(`/api/economic/runs/${enc(runId)}`),
  economicAnalyze: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/economic/analyze', { method: 'POST', body: JSON.stringify(body) }),
  economicScenario: (runId: string, body: Record<string, unknown>) =>
    request<Record<string, any>>(`/api/economic/runs/${enc(runId)}/scenario`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  economicScenarios: (runId: string) =>
    request<Record<string, any>>(`/api/economic/runs/${enc(runId)}/scenarios`),
  economicReplay: (runId: string, asOf: string) =>
    request<Record<string, any>>(`/api/economic/runs/${enc(runId)}/replay${qs({ as_of: asOf })}`),
  economicMemory: () => request<Record<string, any>>('/api/economic/memory'),
  economicSentinel: () => request<Record<string, any>>('/api/economic/sentinel'),
  economicRevision: (observationId: string, body: Record<string, unknown>) =>
    request<Record<string, any>>(`/api/economic/observations/${enc(observationId)}/revise`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  economicBenchmarks: () => request<Record<string, any>>('/api/economic/benchmarks'),
  economicSaveApplication: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/economic/applications', {
      method: 'POST', body: JSON.stringify(body),
    }),
  applicationGallery: () => request<Record<string, any>>('/api/applications'),
  applicationExport: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/applications/export', {
      method: 'POST', body: JSON.stringify(body),
    }),
  applicationInstall: (body: Record<string, unknown>) =>
    request<Record<string, any>>('/api/applications/install', {
      method: 'POST', body: JSON.stringify(body),
    }),
  applicationOpen: (installId: string) =>
    request<Record<string, any>>(`/api/applications/${enc(installId)}/open`),
  applicationVerify: (installId: string) =>
    request<Record<string, any>>(`/api/applications/${enc(installId)}/verify`),
  applicationExecute: (installId: string, inputs: Record<string, unknown> = {}) =>
    request<Record<string, any>>(`/api/applications/${enc(installId)}/execute`, {
      method: 'POST', body: JSON.stringify({ inputs }),
    }),
  applicationFork: (installId: string, body: Record<string, unknown>) =>
    request<Record<string, any>>(`/api/applications/${enc(installId)}/fork`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  applicationUninstall: (installId: string) =>
    request<Record<string, any>>(`/api/applications/${enc(installId)}`, { method: 'DELETE' }),
  applicationDownload: async (installId: string): Promise<Blob> => {
    const response = await fetch(`${BASE}/api/applications/${enc(installId)}/download`)
    if (!response.ok) throw new ApiError(response.status, 'download_failed', 'Package download failed')
    return response.blob()
  },
  equityCoverage: () => request<Record<string, any>>('/api/equity/coverage'),
  equityWorkspace: (identifier: string, options: { asOf?: string | null; mode?: AsOfMode } = {}) =>
    request<Record<string, any>>(
      `/api/equity/${enc(identifier)}/workspace${qs({ as_of: options.asOf, mode: options.mode })}`,
    ),
  equityReadiness: (identifier: string) =>
    request<Record<string, any>>(`/api/equity/${enc(identifier)}/readiness`),
  equityReport: (identifier: string, body: Record<string, unknown> = {}) =>
    request<Record<string, any>>(`/api/equity/${enc(identifier)}/report`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  equityPackage: (identifier: string, body: Record<string, unknown> = {}) =>
    request<Record<string, any>>(`/api/equity/${enc(identifier)}/package`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  equityDownload: async (identifier: string): Promise<Blob> => {
    const response = await fetch(`${BASE}/api/equity/${enc(identifier)}/package.atlas`)
    if (!response.ok) throw new ApiError(response.status, 'download_failed', 'Research package download failed')
    return response.blob()
  },
  domainPacks: () => request<Record<string, any>>('/api/domain-packs'),
} satisfies Record<string, unknown>

export type { Mode }
