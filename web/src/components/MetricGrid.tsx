import { useState } from 'react'
import type { Metric, MetricsResponse } from '../types'
import { fmtDate, fmtUnit } from '../format'
import { Badge } from './ui'

const ORDER = [
  'revenue',
  'revenue_growth',
  'gross_margin',
  'operating_margin',
  'net_margin',
  'net_income',
  'eps_diluted',
  'operating_cash_flow',
  'free_cash_flow',
  'assets',
  'liabilities',
  'equity',
  'total_debt',
  'cash_and_equivalents',
  'market_cap',
  'pe',
  'ps',
  'ev',
  'ev_revenue',
  'research_and_development',
]

const PRIMARY = new Set(['revenue', 'net_income', 'operating_margin', 'revenue_growth', 'market_cap', 'pe'])

export default function MetricGrid({
  data,
  onEvidence,
  compact = false,
}: {
  data: MetricsResponse
  onEvidence?: (id: string) => void
  compact?: boolean
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const metrics = Object.values(data.metrics).sort((a, b) => {
    const ai = ORDER.indexOf(a.key)
    const bi = ORDER.indexOf(b.key)
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
  })
  const shown = compact ? metrics.filter((metric) => PRIMARY.has(metric.key)) : metrics

  return (
    <div className="metric-block">
      <div className="metric-meta">
        <Badge tone="accent">{data.period_end ? `FY to ${fmtDate(data.period_end)}` : 'no fiscal period'}</Badge>
        {data.price_as_of && <Badge tone="neutral">price {fmtDate(data.price_as_of)}</Badge>}
        {data.completeness !== 'complete_for_query' && <Badge tone="warn">{data.completeness}</Badge>}
        {data.price_source === 'synthetic' && <Badge tone="synthetic">synthetic price</Badge>}
      </div>
      <div className={`metric-grid ${compact ? 'is-compact' : ''}`}>
        {shown.map((metric) => (
          <article className="metric-card" key={metric.key}>
            <div className="metric-label">{metric.label}</div>
            <div className="metric-value mono">{fmtUnit(metric.value, metric.unit)}</div>
            <div className="metric-foot">
              <span className="muted small">{metric.kind.replace(/_/g, ' ')}</span>
              {(metric.formula || metric.evidence_ids.length > 0) && (
                <button
                  className="link-button small"
                  aria-expanded={expanded === metric.key}
                  onClick={() => setExpanded(expanded === metric.key ? null : metric.key)}
                >
                  {expanded === metric.key ? 'hide' : 'working'}
                </button>
              )}
            </div>
            {expanded === metric.key && <MetricDetail metric={metric} onEvidence={onEvidence} />}
          </article>
        ))}
      </div>
      {data.missing.length > 0 && (
        <p className="muted small">
          Not computed: {data.missing.join(', ')}. A missing input is reported, never estimated.
        </p>
      )}
      {data.notes.map((note, index) => (
        <p className="muted small" key={index}>
          {note}
        </p>
      ))}
    </div>
  )
}

function MetricDetail({ metric, onEvidence }: { metric: Metric; onEvidence?: (id: string) => void }) {
  return (
    <div className="metric-detail">
      {metric.formula && (
        <div className="formula mono small" title="Formula used at read time">
          {metric.formula}
        </div>
      )}
      {metric.note && <p className="small muted">{metric.note}</p>}
      <div className="evidence-list">
        {metric.evidence_ids.map((id) => (
          <button key={id} className="evidence-chip mono" onClick={() => onEvidence?.(id)} title="Open X-Ray">
            {id}
          </button>
        ))}
      </div>
      <div className="muted small">
        {metric.comparison_period_end && <>compared with {fmtDate(metric.comparison_period_end)} · </>}
        {metric.period_end && <>period end {fmtDate(metric.period_end)}</>}
      </div>
    </div>
  )
}
