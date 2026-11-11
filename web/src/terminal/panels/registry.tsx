import { useMemo, useState } from 'react'
import { api } from '../../api'
import Chart from '../../components/Chart'
import StatementTable from '../../components/StatementTable'
import { ErrorState, Loading } from '../../components/ui'
import { fmtDate, fmtNumber, fmtSignedPct, fmtUnit } from '../../format'
import { useAsync, useSettings } from '../../state'
import type { MarketOverviewItem, Metric, StatementCell, StatementRow } from '../../types'
import type { PanelKind } from '../command/registry'
import { missingLink, resolveInstrument, type LinkGroup } from '../links'
import { useLinks } from '../linkContext'

export interface PanelDescriptor {
  id: string
  kind: PanelKind
  title: string
  linkGroup: LinkGroup | null
}

export interface PanelMeta {
  kind: PanelKind
  title: string
  description: string
  accepts: Array<'instrument' | 'security' | 'cutoff' | 'mode'>
  backendType: string
}

export const PANEL_META: Record<PanelKind, PanelMeta> = {
  monitor: {
    kind: 'monitor',
    title: 'Universe monitor',
    description: 'Covered securities with the latest observed close and its data status.',
    accepts: ['cutoff'],
    backendType: 'market-overview',
  },
  chart: {
    kind: 'chart',
    title: 'Price chart',
    description: 'Adjusted price series for the linked security, with its adjustment policy.',
    accepts: ['security', 'cutoff'],
    backendType: 'chart',
  },
  statements: {
    kind: 'statements',
    title: 'Financial statements',
    description: 'Point-in-time statements; every cell can open its evidence.',
    accepts: ['instrument', 'cutoff', 'mode'],
    backendType: 'statements',
  },
  metrics: {
    kind: 'metrics',
    title: 'Valuation metrics',
    description: 'Computed metrics with formula, unit and supporting evidence.',
    accepts: ['instrument', 'cutoff', 'mode'],
    backendType: 'metrics',
  },
  evidence: {
    kind: 'evidence',
    title: 'Evidence inspector',
    description: 'Source, availability, revision chain and limitations for one observation.',
    accepts: [],
    // The inspector itself is persisted without a pinned observation; a saved
    // `xray` panel (which requires an evidence id) still restores as this panel.
    backendType: 'evidence',
  },
  memo: {
    kind: 'memo',
    title: 'Research memo',
    description: 'Saved memo versions, content hashes and change detection.',
    accepts: ['instrument'],
    backendType: 'memo',
  },
  model: {
    kind: 'model',
    title: 'Model registry',
    description: 'Model and indicator versions, schemas and formulas actually registered.',
    accepts: [],
    backendType: 'model',
  },
  diagnostics: {
    kind: 'diagnostics',
    title: 'Diagnostics',
    description: 'Database, schema, integrity and desk context.',
    accepts: ['cutoff', 'mode'],
    backendType: 'diagnostics',
  },
}

export const PANEL_ORDER: PanelKind[] = [
  'monitor',
  'chart',
  'statements',
  'metrics',
  'evidence',
  'memo',
  'model',
  'diagnostics',
]

const BACKEND_TO_KIND: Record<string, PanelKind> = {
  'market-overview': 'monitor',
  chart: 'chart',
  statements: 'statements',
  metrics: 'metrics',
  xray: 'evidence',
  evidence: 'evidence',
  memo: 'memo',
  model: 'model',
  diagnostics: 'diagnostics',
}

export function panelKindFromBackend(type: string): PanelKind | null {
  return BACKEND_TO_KIND[type] ?? null
}

export function backendTypeFor(kind: PanelKind): string {
  return PANEL_META[kind].backendType
}

function PrimitiveList({ value }: { value: Record<string, unknown> | null | undefined }) {
  if (!value) return null
  const entries = Object.entries(value).filter(
    ([, item]) => item === null || ['string', 'number', 'boolean'].includes(typeof item),
  )
  if (!entries.length) return null
  return (
    <dl className="tp-kv">
      {entries.map(([key, item]) => (
        <div key={key} style={{ display: 'contents' }}>
          <dt>{key.replace(/_/g, ' ')}</dt>
          <dd>{item === null ? '—' : String(item)}</dd>
        </div>
      ))}
    </dl>
  )
}

function PanelFrame({
  title,
  meta,
  children,
}: {
  title: string
  meta?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="tp-head">
        <span className="tp-title">{title}</span>
        {meta && <span className="tp-meta">{meta}</span>}
      </div>
      {children}
    </div>
  )
}

export function PanelView({
  descriptor,
  selectedEvidence,
  onEvidence,
  onSelectInstrument,
}: {
  descriptor: PanelDescriptor
  selectedEvidence: string | null
  onEvidence: (evidenceId: string) => void
  onSelectInstrument: (issuerId: string, securityId: string | null) => void
}) {
  switch (descriptor.kind) {
    case 'monitor':
      return <MonitorPanel onSelectInstrument={onSelectInstrument} />
    case 'chart':
      return <ChartPanel descriptor={descriptor} />
    case 'statements':
      return <StatementsPanel descriptor={descriptor} selectedEvidence={selectedEvidence} onEvidence={onEvidence} />
    case 'metrics':
      return <MetricsPanel descriptor={descriptor} onEvidence={onEvidence} />
    case 'evidence':
      return <EvidencePanel evidenceId={selectedEvidence} />
    case 'memo':
      return <MemoPanel descriptor={descriptor} />
    case 'model':
      return <ModelPanel />
    case 'diagnostics':
      return <DiagnosticsPanel />
    default:
      return <div className="tp-empty">Unknown panel.</div>
  }
}

/* ------------------------------------------------------------------ monitor */
function MonitorPanel({ onSelectInstrument }: { onSelectInstrument: (issuerId: string, securityId: string | null) => void }) {
  const overview = useAsync(() => api.markets(), [])
  const [sort, setSort] = useState<{ key: 'ticker' | 'last_close' | 'change_1d'; desc: boolean }>({ key: 'ticker', desc: false })

  const rows = useMemo(() => {
    const items = [...(overview.data?.items ?? [])]
    items.sort((left, right) => {
      const order = sort.desc ? -1 : 1
      if (sort.key === 'ticker') return order * (left.ticker ?? '').localeCompare(right.ticker ?? '')
      const a = sort.key === 'last_close' ? left.last_close : left.change_1d
      const b = sort.key === 'last_close' ? right.last_close : right.change_1d
      if (a === null || a === undefined) return 1
      if (b === null || b === undefined) return -1
      return order * (a - b)
    })
    return items
  }, [overview.data, sort])

  if (overview.loading) return <Loading label="Loading universe" />
  if (overview.error) return <ErrorState error={overview.error} onRetry={overview.reload} />

  const header = (key: 'ticker' | 'last_close' | 'change_1d', label: string, numeric = false) => (
    <th
      className={numeric ? 'numeric' : ''}
      aria-sort={sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none'}
    >
      <button
        className="row-button"
        onClick={() => setSort({ key, desc: sort.key === key ? !sort.desc : false })}
      >
        {label}
      </button>
    </th>
  )

  return (
    <PanelFrame title="Universe" meta={`${overview.data?.count ?? 0} securities · ${fmtDate(overview.data?.as_of)}`}>
      <table className="tp-table">
        <thead>
          <tr>
            {header('ticker', 'Security')}
            {header('last_close', 'Last', true)}
            {header('change_1d', '1D', true)}
            <th className="numeric">1Y</th>
            <th className="numeric">Sessions</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item: MarketOverviewItem) => (
            <tr key={item.security_id} onClick={() => onSelectInstrument(item.issuer_id, item.security_id)}>
              <td>
                <button className="row-button">
                  <span className="tp-label">{item.ticker ?? item.security_id}</span>{' '}
                  <span className="tp-secondary">{item.legal_name?.slice(0, 28)}</span>
                </button>
              </td>
              <td className="numeric">{fmtNumber(item.last_close, 2)}</td>
              <td className="numeric">{fmtSignedPct(item.change_1d)}</td>
              <td className="numeric">{fmtSignedPct(item.change_1y)}</td>
              <td className="numeric">{item.sessions}</td>
              <td>
                <span className={`tp-badge ${item.data_status === 'synthetic' ? 'is-synthetic' : ''}`}>{item.data_status}</span>
              </td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={6} className="tp-empty">
                No priced securities in this database. SEC fundamentals still work; price panels stay empty until an
                authorised import.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {overview.data?.notes?.length ? (
        <p className="tp-empty">{overview.data.notes.join(' ')}</p>
      ) : null}
    </PanelFrame>
  )
}

/* -------------------------------------------------------------------- chart */
function ChartPanel({ descriptor }: { descriptor: PanelDescriptor }) {
  const links = useLinks()
  const { theme } = useSettings()
  const selection = resolveInstrument(links.state, descriptor.linkGroup)
  const [range, setRange] = useState('1Y')
  const securityId = selection.securityId

  const market = useAsync(
    () =>
      securityId
        ? api.market(securityId, { range, view: 'split', indicators: [], asOf: links.state.asOf, chartType: 'line' })
        : Promise.resolve(null),
    [securityId, range, links.state.asOf],
  )

  if (!securityId) {
    return (
      <PanelFrame title="Price chart">
        <p className="tp-empty">{missingLink(links.state, descriptor.linkGroup) ?? 'This instrument has no priced security, so Atlas has no series to draw.'}</p>
      </PanelFrame>
    )
  }
  if (market.loading) return <Loading label="Loading series" />
  if (market.error) return <ErrorState error={market.error} onRetry={market.reload} />
  if (!market.data || !market.data.bars.length) {
    return (
      <PanelFrame title="Price chart">
        <p className="tp-empty">
          No bars for this security at this cutoff. Atlas does not draw a placeholder series.
        </p>
      </PanelFrame>
    )
  }

  return (
    <PanelFrame
      title="Price"
      meta={`${market.data.view} · ${market.data.coverage.first} → ${market.data.coverage.last} · ${market.data.coverage.sessions} sessions`}
    >
      <div className="tp-toolbar">
        {['3M', '6M', '1Y', '2Y', 'MAX'].map((option) => (
          <button
            key={option}
            className={`button ${range === option ? 'button-primary' : ''}`}
            onClick={() => setRange(option)}
          >
            {option}
          </button>
        ))}
        <span className="tp-meta">{market.data.adjustment_status}</span>
      </div>
      <Chart
        bars={market.data.bars}
        indexPoints={market.data.index}
        indicators={market.data.indicators}
        chartType="line"
        theme={theme}
        height={260}
        actions={market.data.actions}
        viewLabel={market.data.view}
      />
      <p className="tp-empty">{market.data.price_basis_note}</p>
    </PanelFrame>
  )
}

/* --------------------------------------------------------------- statements */
function StatementsPanel({
  descriptor,
  selectedEvidence,
  onEvidence,
}: {
  descriptor: PanelDescriptor
  selectedEvidence: string | null
  onEvidence: (evidenceId: string) => void
}) {
  const links = useLinks()
  const selection = resolveInstrument(links.state, descriptor.linkGroup)
  const [statement, setStatement] = useState<'income' | 'balance' | 'cashflow'>('income')
  const [period, setPeriod] = useState<'FY' | 'Q'>('FY')

  const data = useAsync(
    () =>
      selection.issuerId
        ? api.statements(selection.issuerId, {
            statement,
            period,
            asOf: links.state.asOf,
            mode: links.state.mode,
            limit: 5,
          })
        : Promise.resolve(null),
    [selection.issuerId, statement, period, links.state.asOf, links.state.mode],
  )

  if (!selection.issuerId) {
    return (
      <PanelFrame title="Statements">
        <p className="tp-empty">{missingLink(links.state, descriptor.linkGroup)}</p>
      </PanelFrame>
    )
  }
  if (data.loading) return <Loading label="Loading statements" />
  if (data.error) return <ErrorState error={data.error} onRetry={data.reload} />
  if (!data.data) return <div className="tp-empty">No statement returned.</div>

  return (
    <PanelFrame
      title={data.data.issuer.legal_name}
      meta={`${data.data.policy} · ${data.data.completeness}`}
    >
      <div className="tp-toolbar">
        {(['income', 'balance', 'cashflow'] as const).map((option) => (
          <button
            key={option}
            className={`button ${statement === option ? 'button-primary' : ''}`}
            onClick={() => setStatement(option)}
          >
            {option}
          </button>
        ))}
        {(['FY', 'Q'] as const).map((option) => (
          <button
            key={option}
            className={`button ${period === option ? 'button-primary' : ''}`}
            onClick={() => setPeriod(option)}
          >
            {option}
          </button>
        ))}
        <span className="tp-meta">
          as of {data.data.as_of} · excluded {data.data.excluded_not_yet_available} not-yet-available
        </span>
      </div>
      <StatementTable
        data={data.data}
        selectedEvidence={selectedEvidence}
        onSelect={(cell: StatementCell, _row: StatementRow) => {
          if (cell.evidence_id) onEvidence(cell.evidence_id)
        }}
      />
      {data.data.contradictions.length > 0 && (
        <p className="tp-error">
          {data.data.contradictions.length} contradictory observations were kept separate, not reconciled.
        </p>
      )}
    </PanelFrame>
  )
}

/* ------------------------------------------------------------------ metrics */
function MetricsPanel({ descriptor, onEvidence }: { descriptor: PanelDescriptor; onEvidence: (id: string) => void }) {
  const links = useLinks()
  const selection = resolveInstrument(links.state, descriptor.linkGroup)
  const data = useAsync(
    () =>
      selection.issuerId
        ? api.metrics(selection.issuerId, { asOf: links.state.asOf, mode: links.state.mode })
        : Promise.resolve(null),
    [selection.issuerId, links.state.asOf, links.state.mode],
  )

  if (!selection.issuerId) {
    return (
      <PanelFrame title="Valuation metrics">
        <p className="tp-empty">{missingLink(links.state, descriptor.linkGroup)}</p>
      </PanelFrame>
    )
  }
  if (data.loading) return <Loading label="Loading metrics" />
  if (data.error) return <ErrorState error={data.error} onRetry={data.reload} />
  if (!data.data) return <div className="tp-empty">No metrics returned.</div>

  const metrics: Metric[] = Object.values(data.data.metrics ?? {})

  return (
    <PanelFrame
      title="Metrics"
      meta={`${data.data.period_end ?? 'no period'} · price ${data.data.price_as_of ?? '—'} · ${data.data.completeness}`}
    >
      <table className="tp-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th className="numeric">Value</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((metric: Metric) => (
            <tr key={metric.key}>
              <td>
                <span className="tp-label">{metric.label}</span>
                {metric.formula && <div className="tp-secondary">{metric.formula}</div>}
              </td>
              <td className="numeric">{metric.text ?? fmtUnit(metric.value, metric.unit)}</td>
              <td>
                {metric.evidence_ids?.slice(0, 2).map((evidenceId) => (
                  <button key={evidenceId} className="evidence-chip" onClick={() => onEvidence(evidenceId)}>
                    {evidenceId.slice(0, 8)}
                  </button>
                ))}
                {(metric.evidence_ids?.length ?? 0) > 2 && (
                  <span className="tp-secondary"> +{(metric.evidence_ids?.length ?? 0) - 2}</span>
                )}
              </td>
            </tr>
          ))}
          {!metrics.length && (
            <tr>
              <td colSpan={3} className="tp-empty">
                No metric is computable from the evidence available at this cutoff.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {data.data.missing?.length ? (
        <p className="tp-empty">Missing: {data.data.missing.join(', ')}</p>
      ) : null}
    </PanelFrame>
  )
}

/* ----------------------------------------------------------------- evidence */
function EvidencePanel({ evidenceId }: { evidenceId: string | null }) {
  const xray = useAsync(() => (evidenceId ? api.xray(evidenceId) : Promise.resolve(null)), [evidenceId])

  if (!evidenceId) {
    return (
      <PanelFrame title="Evidence">
        <p className="tp-empty">
          Select a value in a statements or metrics panel. Every displayed financial observation keeps its evidence,
          and this panel shows it.
        </p>
      </PanelFrame>
    )
  }
  if (xray.loading) return <Loading label="Loading evidence" />
  if (xray.error) return <ErrorState error={xray.error} onRetry={xray.reload} />
  if (!xray.data) return <div className="tp-empty">No evidence returned.</div>

  const record = xray.data.record
  return (
    <PanelFrame title={record.concept ?? evidenceId} meta={xray.data.terminal.schema}>
      <dl className="tp-kv">
        <dt>value</dt>
        <dd>
          {record.value ?? '—'} {record.unit ?? ''}
        </dd>
        <dt>period</dt>
        <dd>
          {record.period_start ?? '—'} → {record.period_end ?? '—'}
        </dd>
        <dt>available</dt>
        <dd>
          {record.availability_time ?? 'unknown'} ({record.availability_precision ?? 'unknown'})
        </dd>
        <dt>quality</dt>
        <dd>{record.quality ?? '—'}</dd>
        <dt>source</dt>
        <dd>
          {xray.data.source.name ?? xray.data.source.source_id ?? '—'} · {xray.data.source.kind ?? '—'}
        </dd>
        <dt>licence</dt>
        <dd>{xray.data.source.licence ?? 'not declared'}</dd>
        <dt>derivation</dt>
        <dd>{record.derivation_rule ?? record.derivation_kind ?? 'reported'}</dd>
        <dt>filing</dt>
        <dd>{record.accession_number ?? '—'}</dd>
      </dl>
      {xray.data.revision_chain.length > 1 && (
        <p className="tp-empty">
          Revision chain: {xray.data.revision_chain.length} observations kept, newest first.
        </p>
      )}
      {xray.data.limitations.length > 0 && (
        <ul className="tp-empty">
          {xray.data.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      )}
    </PanelFrame>
  )
}

/* --------------------------------------------------------------------- memo */
function MemoPanel({ descriptor }: { descriptor: PanelDescriptor }) {
  const links = useLinks()
  const selection = resolveInstrument(links.state, descriptor.linkGroup)
  const memos = useAsync(() => api.researchMemos(), [])
  const [checked, setChecked] = useState<Record<string, unknown> | null>(null)
  const [busy, setBusy] = useState(false)

  if (memos.loading) return <Loading label="Loading memos" />
  if (memos.error) return <ErrorState error={memos.error} onRetry={memos.reload} />

  const items: Array<Record<string, unknown>> = Array.isArray((memos.data as { items?: unknown })?.items)
    ? ((memos.data as { items: Array<Record<string, unknown>> }).items)
    : []
  const filtered = selection.issuerId
    ? items.filter((item) => String(item.issuer_id ?? item.issuerId ?? '') === selection.issuerId || !item.issuer_id)
    : items

  return (
    <PanelFrame title="Saved memos" meta={`${filtered.length} version(s)`}>
      <table className="tp-table">
        <thead>
          <tr>
            <th>Object</th>
            <th>Version</th>
            <th>Hash</th>
            <th>Saved</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {filtered.slice(0, 12).map((item, index) => {
            const id = String(item.object_id ?? item.id ?? `memo-${index}`)
            return (
              <tr key={id}>
                <td className="tp-mono">
                  <span className="tp-clip" title={id}>
                    {id}
                  </span>
                </td>
                <td className="tp-mono">{String(item.version ?? '—')}</td>
                <td className="tp-mono">
                  <span className="tp-clip" title={String(item.content_hash ?? '')}>
                    {String(item.content_hash ?? '—')}
                  </span>
                </td>
                <td className="tp-mono">
                  <span className="tp-clip">{fmtDate(String(item.created_at ?? item.saved_at ?? ''))}</span>
                </td>
                <td>
                  <button
                    className="button"
                    disabled={busy}
                    onClick={() => {
                      setBusy(true)
                      api
                        .researchMemoCheck(id)
                        .then((result) => setChecked(result))
                        .catch((error: Error) => setChecked({ error: error.message }))
                        .finally(() => setBusy(false))
                    }}
                  >
                    Check
                  </button>
                </td>
              </tr>
            )
          })}
          {!filtered.length && (
            <tr>
              <td colSpan={5} className="tp-empty">
                No saved memo for this instrument. Build one in Research → Equity research; nothing is generated here.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {checked && <PrimitiveList value={checked} />}
    </PanelFrame>
  )
}

/* -------------------------------------------------------------------- model */
function ModelPanel() {
  const schema = useAsync(() => api.schema(), [])
  const indicators = useAsync(() => api.indicators(), [])

  if (schema.loading) return <Loading label="Loading model registry" />
  if (schema.error) return <ErrorState error={schema.error} onRetry={schema.reload} />

  return (
    <PanelFrame title="Registered models" meta="read from /api/schema">
      <PrimitiveList value={schema.data as Record<string, unknown>} />
      <p className="tp-title" style={{ marginTop: 12 }}>
        Indicators
      </p>
      <table className="tp-table">
        <thead>
          <tr>
            <th>Key</th>
            <th>Version</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries((schema.data as { indicator_versions?: Record<string, string> })?.indicator_versions ?? {}).map(
            ([key, version]) => (
              <tr key={key}>
                <td className="tp-label">{key}</td>
                <td className="tp-mono">{version}</td>
              </tr>
            ),
          )}
          {!Object.keys((schema.data as { indicator_versions?: Record<string, string> })?.indicator_versions ?? {}).length && (
            <tr>
              <td colSpan={2} className="tp-empty">
                The service returned no indicator registry.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {indicators.error && <p className="tp-error">Indicator list unavailable: {indicators.error.message}</p>}
    </PanelFrame>
  )
}

/* --------------------------------------------------------------- diagnostics */
function DiagnosticsPanel() {
  const health = useAsync(() => api.health(), [])
  const schema = useAsync(() => api.schema(), [])
  const links = useLinks()

  if (health.loading) return <Loading label="Loading diagnostics" />
  if (health.error) return <ErrorState error={health.error} onRetry={health.reload} />

  const payload = (health.data ?? {}) as Record<string, unknown>
  return (
    <PanelFrame title="Runtime" meta={String(payload.status ?? 'unknown')}>
      <PrimitiveList value={payload} />
      <p className="tp-title" style={{ marginTop: 12 }}>
        Desk context
      </p>
      <dl className="tp-kv">
        <dt>link group</dt>
        <dd>{links.state.activeGroup}</dd>
        <dt>cutoff</dt>
        <dd>{links.state.asOf ?? 'latest available'}</dd>
        <dt>mode</dt>
        <dd>{links.state.mode}</dd>
        <dt>terminal schema</dt>
        <dd>{String((schema.data as Record<string, unknown>)?.terminal_schema ?? '—')}</dd>
        <dt>workspace schema</dt>
        <dd>{String((schema.data as Record<string, unknown>)?.workspace_layout_schema ?? '—')}</dd>
      </dl>
    </PanelFrame>
  )
}
