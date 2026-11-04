import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import Chart from '../components/Chart'
import CompanyHeader from '../components/CompanyHeader'
import FilingsTable from '../components/FilingsTable'
import MetricGrid from '../components/MetricGrid'
import StatementTable from '../components/StatementTable'
import XrayPanel from '../components/XrayPanel'
import { Badge, ErrorState, Loading } from '../components/ui'
import { fmtCompact, fmtDate, fmtSignedPct, fmtUnit, toneForNumber } from '../format'
import { useAsync, useSettings } from '../state'
import type { PanelConfig, StatementsResponse, Watchlist, Workspace } from '../types'

const ADDABLE = [
  { type: 'chart', label: 'Price chart' },
  { type: 'statements', label: 'Financial statements' },
  { type: 'metrics', label: 'Key metrics' },
  { type: 'filings', label: 'Filings' },
  { type: 'company-header', label: 'Company header' },
  { type: 'market-overview', label: 'Market overview' },
  { type: 'indicator-controls', label: 'Indicator controls' },
]

export default function WorkspaceView() {
  const { workspaceId = '' } = useParams()
  const loaded = useAsync(() => api.workspace(workspaceId), [workspaceId])
  const [document, setDocument] = useState<Workspace | null>(null)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [editing, setEditing] = useState(true)
  const [newType, setNewType] = useState('chart')

  const current = document ?? loaded.data
  const defaults = useMemo(() => {
    const issuer = current?.document.panels.find((panel) => panel.issuer_id)?.issuer_id
    const security = current?.document.panels.find((panel) => panel.security_id)?.security_id
    return { issuer, security }
  }, [current])

  if (loaded.loading) return <div className="page"><Loading label="Opening workspace" /></div>
  if (loaded.error) return <div className="page"><ErrorState error={loaded.error} onRetry={loaded.reload} /></div>
  if (!current) return <div className="page"><ErrorState error={new Error('Workspace not found')} /></div>

  function update(mutator: (copy: Workspace) => void) {
    const snapshot = JSON.parse(JSON.stringify(current)) as Workspace
    mutator(snapshot)
    setDocument(snapshot)
    setDirty(true)
  }

  async function save() {
    if (!current) return
    setError(null)
    try {
      const saved = await api.updateWorkspace(current.workspace_id, {
        ...current.document,
        name: current.name,
        mode: current.mode,
        columns: current.document.columns,
        panels: current.document.panels,
      })
      setDocument(saved)
      setDirty(false)
    } catch (caught) {
      setError(caught as Error)
    }
  }

  function addPanel() {
    const needsIssuer = ['company-header', 'statements', 'metrics', 'filings'].includes(newType)
    const needsSecurity = newType === 'chart'
    if ((needsIssuer && !defaults.issuer) || (needsSecurity && !defaults.security)) {
      setError(new Error('Add a company panel first so new panels know which entity to show.'))
      return
    }
    const id = `p${Math.random().toString(36).slice(2, 8)}`
    update((copy) => {
      copy.document.panels.push({
        id,
        type: newType,
        title: ADDABLE.find((item) => item.type === newType)?.label ?? newType,
        span: 1,
        config: {},
        ...(needsIssuer ? { issuer_id: defaults.issuer } : {}),
        ...(needsSecurity ? { security_id: defaults.security } : {}),
      })
    })
  }

  return (
    <div className="page">
      <div className="workspace-header">
        <div>
          <div className="eyebrow">Workspace · {current.schema}</div>
          <h1>{current.name}</h1>
          <div className="muted small">
            {current.document.panels.length} panels · {current.document.columns} columns · fingerprint {current.fingerprint}
          </div>
        </div>
        <div className="toolbar-right">
          <Badge tone={dirty ? 'warn' : 'positive'}>{dirty ? 'unsaved changes' : 'saved'}</Badge>
          <button className="button" onClick={() => setEditing((value) => !value)}>
            {editing ? 'Done editing' : 'Edit layout'}
          </button>
          <button className="button button-primary" onClick={() => void save()} disabled={!dirty}>
            Save
          </button>
          <Link className="button" to="/workspaces">
            All workspaces
          </Link>
        </div>
      </div>
      {error && <ErrorState error={error} />}

      {editing && (
        <div className="toolbar wrap workspace-editbar">
          <label className="inline-field small">
            Columns
            <select
              className="field"
              value={current.document.columns}
              onChange={(event) =>
                update((copy) => {
                  copy.document.columns = Number(event.target.value)
                  copy.document.panels.forEach((panel) => {
                    panel.span = Math.min(panel.span, copy.document.columns)
                  })
                })
              }
            >
              {[1, 2, 3, 4].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field small">
            Add panel
            <select className="field" value={newType} onChange={(event) => setNewType(event.target.value)}>
              {ADDABLE.map((item) => (
                <option key={item.type} value={item.type}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <button className="button" onClick={addPanel}>
            Add
          </button>
          <span className="muted small">
            Panel changes are validated on save; unknown types or fields are rejected by the server.
          </span>
        </div>
      )}

      <div className="workspace-grid" style={{ gridTemplateColumns: `repeat(${current.document.columns}, minmax(0, 1fr))` }}>
        {current.document.panels.map((panel, index) => (
          <section
            key={panel.id}
            className="panel"
            style={{ gridColumn: `span ${Math.min(panel.span, current.document.columns)}` }}
          >
            <header className="panel-head">
              <div>
                <span className="panel-type mono small">{panel.type}</span>
                <h3>{panel.title}</h3>
              </div>
              {editing && (
                <div className="panel-controls">
                  <button className="icon-button" aria-label="Move panel earlier" disabled={index === 0} onClick={() => update((copy) => {
                    const [moved] = copy.document.panels.splice(index, 1)
                    copy.document.panels.splice(index - 1, 0, moved)
                  })}>↑</button>
                  <button className="icon-button" aria-label="Move panel later" disabled={index === current.document.panels.length - 1} onClick={() => update((copy) => {
                    const [moved] = copy.document.panels.splice(index, 1)
                    copy.document.panels.splice(index + 1, 0, moved)
                  })}>↓</button>
                  <button className="icon-button" aria-label="Decrease width" disabled={panel.span <= 1} onClick={() => update((copy) => { copy.document.panels[index].span -= 1 })}>−</button>
                  <button className="icon-button" aria-label="Increase width" disabled={panel.span >= current.document.columns} onClick={() => update((copy) => { copy.document.panels[index].span += 1 })}>+</button>
                  <button className="icon-button" aria-label="Remove panel" onClick={() => update((copy) => { copy.document.panels.splice(index, 1) })}>✕</button>
                </div>
              )}
            </header>
            <div className="panel-body">
              <PanelBody panel={panel} />
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}

function PanelBody({ panel }: { panel: PanelConfig }) {
  switch (panel.type) {
    case 'company-header':
      return <HeaderPanel issuerId={panel.issuer_id} />
    case 'chart':
      return <ChartPanel panel={panel} />
    case 'statements':
      return <StatementsPanel panel={panel} />
    case 'metrics':
      return <MetricsPanel panel={panel} />
    case 'filings':
      return <FilingsPanel panel={panel} />
    case 'market-overview':
      return <OverviewPanel />
    case 'watchlist':
      return <WatchlistPanel panel={panel} />
    case 'screener':
      return <ScreenerPanel panel={panel} />
    case 'xray':
      return <XrayPanelPanel panel={panel} />
    case 'indicator-controls':
      return <IndicatorPanel panel={panel} />
    default:
      return <p className="muted small">Unknown panel type “{panel.type}”.</p>
  }
}

function HeaderPanel({ issuerId }: { issuerId?: string }) {
  const { data, error, loading } = useAsync(() => (issuerId ? api.company(issuerId) : Promise.resolve(null)), [issuerId])
  if (!issuerId) return <p className="muted small">No issuer configured.</p>
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  return <CompanyHeader company={data} />
}

function ChartPanel({ panel }: { panel: PanelConfig }) {
  const { theme } = useSettings()
  const config = panel.config as { view?: 'raw' | 'split' | 'total_return'; range?: string; chart_type?: string; indicators?: Array<{ key: string; params?: Record<string, number> }> }
  const securityId = panel.security_id
  const indicators = config.indicators ?? [{ key: 'sma', params: { window: 50 } }]
  const { data, error, loading } = useAsync(
    () =>
      securityId
        ? api.market(securityId, {
            range: config.range ?? '1Y',
            view: config.view ?? 'split',
            indicators,
          })
        : Promise.resolve(null),
    [securityId, config.range, config.view, JSON.stringify(indicators)],
  )
  if (!securityId) return <p className="muted small">No security configured.</p>
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  return (
    <>
      <Chart
        bars={data.bars}
        indexPoints={data.index}
        indicators={data.indicators}
        chartType={(config.chart_type as 'candlestick' | 'line' | 'area') ?? 'candlestick'}
        theme={theme}
        viewLabel={data.view === 'total_return' ? 'TOTAL-RETURN INDEX' : data.view === 'split' ? 'SPLIT-ADJUSTED' : 'RAW'}
        actions={data.actions}
        height={320}
      />
      <p className="muted small">{data.price_basis_note}</p>
    </>
  )
}

function StatementsPanel({ panel }: { panel: PanelConfig }) {
  const config = panel.config as { statement?: string; period?: 'FY' | 'Q'; limit?: number; mode?: 'public_available' | 'atlas_ingested' }
  const [evidenceId, setEvidenceId] = useState<string | null>(null)
  const { data, error, loading } = useAsync(
    () =>
      panel.issuer_id
        ? api.statements(panel.issuer_id, {
            statement: config.statement ?? 'income',
            period: config.period ?? 'FY',
            mode: config.mode ?? 'public_available',
            limit: config.limit ?? 5,
          })
        : Promise.resolve(null),
    [panel.issuer_id, config.statement, config.period, config.mode, config.limit],
  )
  if (!panel.issuer_id) return <p className="muted small">No issuer configured.</p>
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  return (
    <>
      <StatementTable data={data as StatementsResponse} onSelect={(cell) => cell.evidence_id && setEvidenceId(cell.evidence_id)} selectedEvidence={evidenceId} />
      {evidenceId && <XrayPanel evidenceId={evidenceId} onClose={() => setEvidenceId(null)} inline />}
    </>
  )
}

function MetricsPanel({ panel }: { panel: PanelConfig }) {
  const config = panel.config as { as_of?: string | null; mode?: 'public_available' | 'atlas_ingested' }
  const { data, error, loading } = useAsync(
    () => (panel.issuer_id ? api.metrics(panel.issuer_id, { asOf: config.as_of ?? null, mode: config.mode ?? 'public_available' }) : Promise.resolve(null)),
    [panel.issuer_id, config.as_of, config.mode],
  )
  if (!panel.issuer_id) return <p className="muted small">No issuer configured.</p>
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  return <MetricGrid data={data} compact />
}

function FilingsPanel({ panel }: { panel: PanelConfig }) {
  const config = panel.config as { limit?: number }
  const { data, error, loading } = useAsync(
    () => (panel.issuer_id ? api.filings(panel.issuer_id, { limit: config.limit ?? 12 }) : Promise.resolve(null)),
    [panel.issuer_id, config.limit],
  )
  if (!panel.issuer_id) return <p className="muted small">No issuer configured.</p>
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  return <FilingsTable data={data} />
}

function OverviewPanel() {
  const { data, error, loading } = useAsync(() => api.markets(), [])
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  return (
    <table className="mini-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th className="numeric">Last</th>
          <th className="numeric">1D</th>
          <th>Session</th>
        </tr>
      </thead>
      <tbody>
        {data.items.map((item) => (
          <tr key={item.security_id}>
            <td className="mono">{item.ticker ?? '—'}</td>
            <td className="numeric mono">{fmtCompact(item.last_close)}</td>
            <td className={`numeric mono ${toneForNumber(item.change_1d)}`}>{item.change_1d == null ? '—' : fmtSignedPct(item.change_1d)}</td>
            <td className="mono small">{fmtDate(item.last_bar_date)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function WatchlistPanel({ panel }: { panel: PanelConfig }) {
  const config = panel.config as { columns?: string[]; watchlist_id?: string }
  const { data, error, loading } = useAsync(() => api.watchlists(), [])
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  const list: Watchlist | undefined = data?.items.find((item) => item.watchlist_id === (panel.watchlist_id ?? ''))
  if (!list) return <p className="muted small">Watchlist not configured or no longer exists.</p>
  const columns = config.columns ?? ['ticker', 'last', 'change_1d']
  return (
    <table className="mini-table">
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column} className={column === 'ticker' ? '' : 'numeric'}>
              {column.replace('_', ' ')}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {list.items.map((item) => (
          <tr key={item.security_id}>
            {columns.map((column) => (
              <td key={column} className={column === 'ticker' ? 'mono' : 'numeric mono'}>
                {column === 'ticker' ? item.ticker ?? '—' : column === 'revenue' ? '—' : '—'}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ScreenerPanel({ panel }: { panel: PanelConfig }) {
  const config = panel.config as { filters?: Array<{ metric: string; op: string; value: number }>; match?: 'AND' | 'OR'; sort?: { metric: string; direction: 'asc' | 'desc' } | null }
  const { data, error, loading } = useAsync(
    () => api.screen({ filters: config.filters ?? [], match: config.match ?? 'AND', sort: config.sort ?? null, limit: 20 }),
    [JSON.stringify(config)],
  )
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  if (!data) return null
  return (
    <table className="mini-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Company</th>
          <th className="numeric">Revenue</th>
        </tr>
      </thead>
      <tbody>
        {data.rows.map((row) => (
          <tr key={row.issuer_id}>
            <td className="mono">{row.ticker ?? '—'}</td>
            <td>{row.legal_name}</td>
            <td className="numeric mono">{row.metrics.revenue ? fmtUnit(row.metrics.revenue.value, row.metrics.revenue.unit) : '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function XrayPanelPanel({ panel }: { panel: PanelConfig }) {
  const [evidenceId, setEvidenceId] = useState<string>((panel.config as { evidence_id?: string }).evidence_id ?? '')
  return (
    <div>
      <div className="inline-form">
        <input
          className="field mono"
          placeholder="Evidence id (EV-…)"
          value={evidenceId}
          onChange={(event) => setEvidenceId(event.target.value.trim())}
          aria-label="Evidence id"
        />
      </div>
      {evidenceId ? <XrayPanel evidenceId={evidenceId} inline /> : <p className="muted small">Paste an evidence id, or click a value in a statement panel.</p>}
    </div>
  )
}

function IndicatorPanel({ panel }: { panel: PanelConfig }) {
  const { data, error, loading } = useAsync(() => api.indicators(), [])
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  const key = (panel.config as { indicator?: string }).indicator ?? 'rsi'
  const spec = data?.items.find((item) => item.key === key)
  if (!spec) return <p className="muted small">Unknown indicator.</p>
  const params = spec.params as Array<{ name: string; default: number; minimum: number; maximum: number; description: string }>
  return (
    <div className="small">
      <p>{String(spec.description)}</p>
      <p className="mono small muted">{String(spec.formula)}</p>
      <table className="mini-table">
        <thead>
          <tr>
            <th>Parameter</th>
            <th className="numeric">Default</th>
            <th className="numeric">Range</th>
          </tr>
        </thead>
        <tbody>
          {params.map((param) => (
            <tr key={param.name}>
              <td>{param.name}</td>
              <td className="numeric mono">{param.default}</td>
              <td className="numeric mono">
                {param.minimum}–{param.maximum}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
