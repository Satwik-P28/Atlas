import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useAsync } from '../state'
import { fmtUnit } from '../format'
import { Badge, ErrorState, Loading, SectionHeader } from '../components/ui'
import type { ScreenerResponse } from '../types'

interface FilterRow {
  metric: string
  op: string
  value: string
  value2: string
}

const DEFAULT_FILTERS: FilterRow[] = [{ metric: 'net_margin', op: 'gt', value: '0', value2: '' }]

export default function Screener() {
  const catalog = useAsync(() => api.screenerMetrics(), [])
  const [filters, setFilters] = useState<FilterRow[]>(DEFAULT_FILTERS)
  const [match, setMatch] = useState<'AND' | 'OR'>('AND')
  const [sortMetric, setSortMetric] = useState('market_cap')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')
  const [result, setResult] = useState<ScreenerResponse | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [running, setRunning] = useState(false)

  const metrics = catalog.data?.items ?? []

  useEffect(() => {
    if (metrics.length > 0) void run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metrics.length])

  async function run() {
    setRunning(true)
    setError(null)
    try {
      const payload = await api.screen({
        filters: filters.map((row) => ({
          metric: row.metric,
          op: row.op,
          value: Number(row.value || 0),
          ...(row.op === 'between' ? { value2: Number(row.value2 || 0) } : {}),
        })),
        match,
        sort: sortMetric ? { metric: sortMetric, direction: sortDirection } : null,
        limit: 100,
      })
      setResult(payload)
    } catch (caught) {
      setError(caught as Error)
    } finally {
      setRunning(false)
    }
  }

  const columns = useMemo(() => {
    if (!result) return []
    const keys = ['market_cap', 'net_margin', 'operating_margin', 'revenue', 'revenue_growth', 'pe', 'ps']
    return keys.filter((key) => result.rows.some((row) => row.metrics[key]?.value != null))
  }, [result])

  function exportCsv() {
    if (!result) return
    const header = ['ticker', 'company', ...columns]
    const lines = result.rows.map((row) => [
      row.ticker ?? '',
      `"${row.legal_name.replace(/"/g, '""')}"`,
      ...columns.map((key) => row.metrics[key]?.value ?? ''),
    ])
    const blob = new Blob([[header.join(','), ...lines.map((line) => line.join(','))].join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'atlas-screen.csv'
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="page">
      <SectionHeader
        eyebrow="Screeners"
        title="Screen the stored universe"
        detail="Every filter is deterministic and evaluated against point-in-time metrics. Missing inputs fail a filter; they are never treated as zero."
        actions={<Badge tone="neutral">{metrics.length} metrics</Badge>}
      />

      <section className="card">
        <div className="toolbar wrap">
          <div className="segmented">
            {(['AND', 'OR'] as const).map((option) => (
              <button key={option} className={match === option ? 'is-selected' : ''} onClick={() => setMatch(option)}>
                {option}
              </button>
            ))}
          </div>
          <label className="inline-field small">
            Sort
            <select className="field" value={sortMetric} onChange={(event) => setSortMetric(event.target.value)}>
              {metrics.map((metric) => (
                <option key={metric.key} value={metric.key}>
                  {metric.label}
                </option>
              ))}
            </select>
          </label>
          <select className="field" value={sortDirection} onChange={(event) => setSortDirection(event.target.value as 'asc' | 'desc')}>
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </select>
          <button className="button button-primary" onClick={run} disabled={running}>
            {running ? 'Running…' : 'Run screen'}
          </button>
          <button className="button" onClick={exportCsv} disabled={!result || result.rows.length === 0}>
            Export CSV
          </button>
        </div>

        <div className="filter-list">
          {filters.map((row, index) => (
            <div className="filter-row" key={index}>
              <select
                className="field"
                value={row.metric}
                aria-label="Filter metric"
                onChange={(event) =>
                  setFilters((current) => current.map((item, i) => (i === index ? { ...item, metric: event.target.value } : item)))
                }
              >
                {metrics.map((metric) => (
                  <option key={metric.key} value={metric.key}>
                    {metric.label} ({metric.unit})
                  </option>
                ))}
              </select>
              <select
                className="field"
                value={row.op}
                aria-label="Comparison"
                onChange={(event) =>
                  setFilters((current) => current.map((item, i) => (i === index ? { ...item, op: event.target.value } : item)))
                }
              >
                <option value="gt">&gt;</option>
                <option value="gte">≥</option>
                <option value="lt">&lt;</option>
                <option value="lte">≤</option>
                <option value="eq">=</option>
                <option value="between">between</option>
              </select>
              <input
                className="field mono"
                type="number"
                step="any"
                value={row.value}
                aria-label="Filter value"
                onChange={(event) =>
                  setFilters((current) => current.map((item, i) => (i === index ? { ...item, value: event.target.value } : item)))
                }
              />
              {row.op === 'between' && (
                <input
                  className="field mono"
                  type="number"
                  step="any"
                  value={row.value2}
                  aria-label="Upper bound"
                  onChange={(event) =>
                    setFilters((current) => current.map((item, i) => (i === index ? { ...item, value2: event.target.value } : item)))
                  }
                />
              )}
              <button
                className="icon-button"
                aria-label="Remove filter"
                onClick={() => setFilters((current) => current.filter((_, i) => i !== index))}
              >
                ✕
              </button>
            </div>
          ))}
          <button
            className="link-button"
            onClick={() => setFilters((current) => [...current, { metric: 'revenue', op: 'gt', value: '0', value2: '' }])}
          >
            + Add filter
          </button>
        </div>
        {metrics.length > 0 && (
          <p className="muted small">
            Units: {Array.from(new Set(metrics.map((metric) => metric.unit))).join(', ')}. Values must be entered in the
            metric's own unit, so a 20% margin is <span className="mono">0.2</span>.
          </p>
        )}
      </section>

      {error && <ErrorState error={error} />}
      {running && !result && <Loading label="Evaluating screen" />}
      {result && (
        <section className="card">
          <div className="screener-summary">
            <div>
              <span className="stat-value mono">{result.matched}</span>
              <span className="stat-label">matches</span>
            </div>
            <div>
              <span className="stat-value mono">{result.universe.issuers_in_database}</span>
              <span className="stat-label">issuers in database</span>
            </div>
            <div>
              <span className="stat-value mono">{result.universe.excluded_for_missing_inputs}</span>
              <span className="stat-label">excluded for missing inputs</span>
            </div>
            <div>
              <span className="stat-value mono">{result.as_of.slice(0, 10)}</span>
              <span className="stat-label">information date</span>
            </div>
          </div>
          <div className="banner banner-info">{result.universe.note}</div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Company</th>
                  {columns.map((key) => (
                    <th key={key} className="numeric">
                      {metrics.find((metric) => metric.key === key)?.label ?? key}
                    </th>
                  ))}
                  <th className="numeric">FY end</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row) => (
                  <tr key={row.issuer_id}>
                    <td className="mono">{row.ticker ?? '—'}</td>
                    <td>{row.legal_name}</td>
                    {columns.map((key) => (
                      <td key={key} className="numeric mono">
                        {row.metrics[key]?.value == null ? '—' : fmtUnit(row.metrics[key].value, row.metrics[key].unit)}
                      </td>
                    ))}
                    <td className="numeric mono small">{row.period_end ?? '—'}</td>
                  </tr>
                ))}
                {result.rows.length === 0 && (
                  <tr>
                    <td colSpan={columns.length + 3} className="muted">
                      No stored issuer satisfies these filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {result.skipped.length > 0 && (
            <details className="small muted">
              <summary>Issuers excluded for missing inputs</summary>
              <ul className="plain">
                {result.skipped.map((entry) => (
                  <li key={entry.issuer_id}>
                    {entry.legal_name}: {entry.missing.join(', ')}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}
    </div>
  )
}
