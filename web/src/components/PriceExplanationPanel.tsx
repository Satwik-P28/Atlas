import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useAsync } from '../state'
import type {
  PriceExplanation,
  PriceExplanationBasis,
  PriceExplanationEvent,
  PriceExplanationMode,
  PriceExplanationRequest,
} from '../types'
import { fmtDate, fmtDateTime, fmtNumber, fmtSignedPct, toneForNumber } from '../format'
import { Badge, ErrorState, Loading } from './ui'
import type { SessionSelection } from './chartSelection'

const BASIS_LABEL: Record<PriceExplanationBasis, string> = {
  price: 'Raw price',
  split_adjusted: 'Split-adjusted',
  total_return: 'Total return',
}

interface Props {
  securityId: string
  selection: SessionSelection
  basis: PriceExplanationBasis
  advanced: boolean
  onBasisChange: (basis: PriceExplanationBasis) => void
  onClose: () => void
}

function downloadReport(report: PriceExplanation) {
  const payload = JSON.stringify(report, null, 2)
  const blob = new Blob([payload], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  const ticker = report.selection.ticker ?? report.selection.security_id
  anchor.href = url
  anchor.download = `atlas-price-explanation-${ticker}-${report.selection.start_session}-${report.selection.end_session}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

function coverageValue(report: PriceExplanation, key: string): string {
  const coverage = report.events.coverage as Record<string, Record<string, unknown> | undefined>
  const section = coverage[key]
  if (!section) return 'unavailable'
  return String(section.status ?? 'available')
}

export default function PriceExplanationPanel({
  securityId,
  selection,
  basis,
  advanced,
  onBasisChange,
  onClose,
}: Props) {
  const [mode, setMode] = useState<PriceExplanationMode>('retrospective_investigation')
  const [cutoff, setCutoff] = useState<string>(selection.end)
  const [benchmarkId, setBenchmarkId] = useState<string>('')
  const [benchmarks, setBenchmarks] = useState<Array<{ id: string; label: string }>>([])
  const [comparison, setComparison] = useState<{
    start: string
    end: string
    report?: PriceExplanation
    error?: string
    loading?: boolean
  } | null>(null)

  useEffect(() => {
    setCutoff((current) => (current < selection.end ? selection.end : current))
  }, [selection.end])

  useEffect(() => {
    let cancelled = false
    api
      .markets()
      .then((overview) => {
        if (cancelled) return
        setBenchmarks(
          overview.items
            .filter((item) => item.security_id !== securityId)
            .map((item) => ({
              id: item.security_id,
              label: `${item.ticker ?? item.security_id} · ${item.legal_name}`,
            })),
        )
      })
      .catch(() => {
        /* a missing benchmark list must not block the investigation */
      })
    return () => {
      cancelled = true
    }
  }, [securityId])

  const request = useMemo<PriceExplanationRequest>(
    () => ({
      start_session: selection.start,
      end_session: selection.end,
      price_basis: basis,
      mode,
      information_cutoff: mode === 'historical_reconstruction' ? cutoff : null,
      benchmark_security_id: benchmarkId || null,
    }),
    [selection.start, selection.end, basis, mode, cutoff, benchmarkId],
  )

  const key = JSON.stringify(request)
  const { data, error, loading, reload } = useAsync(
    () => api.explainPriceRange(securityId, request),
    [securityId, key],
  )

  async function compare(start: string, end: string) {
    if (!start || !end) return
    setComparison({ start, end, loading: true })
    try {
      const report = await api.explainPriceRange(securityId, {
        ...request,
        start_session: start,
        end_session: end,
      })
      setComparison({ start, end, report })
    } catch (caught) {
      setComparison({ start, end, error: (caught as Error).message })
    }
  }

  return (
    <section className="card price-explanation" aria-label="Price movement investigation">
      <header className="price-explanation-head">
        <div>
          <div className="eyebrow">Explain this move</div>
          <h3>
            {fmtDate(selection.start)} → {fmtDate(selection.end)}
          </h3>
          <p className="muted small">
            A pinned investigation: one provider, one revision per session, evidence filtered by
            publication time.
          </p>
        </div>
        <div className="price-explanation-controls">
          <label className="inline-field small">
            Basis
            <select
              className="field"
              value={basis}
              onChange={(event) => onBasisChange(event.target.value as PriceExplanationBasis)}
            >
              {(Object.keys(BASIS_LABEL) as PriceExplanationBasis[]).map((option) => (
                <option key={option} value={option}>
                  {BASIS_LABEL[option]}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field small">
            Knowledge
            <select
              className="field"
              value={mode}
              onChange={(event) => setMode(event.target.value as PriceExplanationMode)}
            >
              <option value="retrospective_investigation">Today's knowledge</option>
              <option value="historical_reconstruction">As of a cutoff</option>
            </select>
          </label>
          {mode === 'historical_reconstruction' && (
            <label className="inline-field small">
              Cutoff
              <input
                className="field mono"
                type="date"
                min={selection.end}
                value={cutoff}
                onChange={(event) => setCutoff(event.target.value)}
              />
            </label>
          )}
          <label className="inline-field small">
            Benchmark
            <select
              className="field"
              value={benchmarkId}
              onChange={(event) => setBenchmarkId(event.target.value)}
            >
              <option value="">None</option>
              {benchmarks.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <button className="button secondary" onClick={onClose} aria-label="Close investigation">
            Close
          </button>
        </div>
      </header>

      {loading && <Loading label="Reconstructing the interval" />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && (
        <>
          <div className="explain-grid">
            <div className="explain-metric">
              <span className="muted small">Interval return</span>
              <strong className={`mono ${toneForNumber(data.price_statistics.interval_return)}`}>
                {fmtSignedPct(data.price_statistics.interval_return)}
              </strong>
              <span className="muted small">{data.price_statistics.basis_label}</span>
            </div>
            <div className="explain-metric">
              <span className="muted small">Start → end</span>
              <strong className="mono">
                {fmtNumber(data.price_statistics.start_price)} →{' '}
                {fmtNumber(data.price_statistics.end_price)} {data.price_statistics.currency}
              </strong>
              <span className="muted small">
                {data.price_statistics.sessions} session(s) · {data.price_statistics.calendar_days} days
              </span>
            </div>
            <div className="explain-metric">
              <span className="muted small">Annualised volatility</span>
              <strong className="mono">
                {data.price_statistics.annualized_volatility === null
                  ? '—'
                  : fmtSignedPct(data.price_statistics.annualized_volatility)}
              </strong>
              <span className="muted small">sample daily σ × √252</span>
            </div>
            <div className="explain-metric">
              <span className="muted small">Max drawdown</span>
              <strong className="mono">{fmtSignedPct(data.price_statistics.max_drawdown)}</strong>
              <span className="muted small">within the selected interval</span>
            </div>
            <div className="explain-metric">
              <span className="muted small">Volume vs trailing median</span>
              <strong className="mono">
                {data.price_statistics.volume.average_to_trailing_median === null
                  ? '—'
                  : `${fmtNumber(data.price_statistics.volume.average_to_trailing_median)}×`}
              </strong>
              <span className="muted small">
                {data.price_statistics.volume.sessions_with_volume} session(s) with volume
              </span>
            </div>
            <div className="explain-metric">
              <span className="muted small">Sessions</span>
              <strong className="mono">{data.selection.sessions}</strong>
              <span className="muted small">
                {String((data.selection.series as { policy?: string }).policy ?? 'series')}
              </span>
            </div>
          </div>

          <div className="explain-bases small">
            <span>Basis reconciliation:</span>
            <span className="mono">raw {fmtSignedPct(data.price_statistics.basis_reconciliation.raw)}</span>
            <span className="mono">
              split {fmtSignedPct(data.price_statistics.basis_reconciliation.split_adjusted)}
            </span>
            <span className="mono">
              total return {fmtSignedPct(data.price_statistics.basis_reconciliation.total_return)}
            </span>
            <span className="muted">
              {data.price_statistics.basis_reconciliation.splits_in_window} split(s) ·{' '}
              {data.price_statistics.basis_reconciliation.dividends_in_window} dividend(s)
            </span>
          </div>

          <div className="explain-columns">
            <div>
              <h4>What happened</h4>
              {data.events.items.length === 0 ? (
                <p className="muted small">
                  No SEC filing or corporate action in Atlas's store was published inside this
                  interval. Absence of stored evidence is not evidence that nothing happened.
                </p>
              ) : (
                <ol className="event-timeline">
                  {data.events.items.map((event) => (
                    <EventRow key={event.event_id} event={event} />
                  ))}
                </ol>
              )}
              <div className="evidence-coverage small muted">
                <span>Filings: {coverageValue(data, 'sec_filings')}</span>
                <span>Corporate actions: {coverageValue(data, 'corporate_actions')}</span>
                <span>News archive: {coverageValue(data, 'news_archive')}</span>
                <span>Consensus: {coverageValue(data, 'analyst_consensus')}</span>
                <span>Macro calendar: {coverageValue(data, 'macro_releases')}</span>
              </div>
            </div>

            <div>
              <h4>Why it might have happened</h4>
              <p className="muted small">
                Ranked by documented relevance. No hypothesis carries a probability, and none is a
                proven cause.
              </p>
              <ol className="hypothesis-list">
                {data.hypotheses.map((hypothesis) => (
                  <li key={hypothesis.hypothesis_id}>
                    <div className="hypothesis-head">
                      <span className="mono small">#{hypothesis.rank}</span>
                      <Badge tone="warn">{hypothesis.epistemic_status}</Badge>
                      <Badge tone="neutral">{hypothesis.causal_status}</Badge>
                    </div>
                    <p>{hypothesis.statement}</p>
                    <p className="muted small">Relevance: {hypothesis.relevance.basis}</p>
                    <details>
                      <summary className="small">
                        Evidence and limits ({hypothesis.relevance.supporting_evidence.length} record(s))
                      </summary>
                      <ul className="small">
                        {hypothesis.relevance.supporting_evidence.map((evidenceId) => (
                          <li key={evidenceId} className="mono">
                            {evidenceId}
                          </li>
                        ))}
                        {hypothesis.limitations.map((limitation, index) => (
                          <li key={index} className="muted">
                            {limitation}
                          </li>
                        ))}
                      </ul>
                    </details>
                  </li>
                ))}
              </ol>
            </div>
          </div>

          <details className="explain-detail" open={advanced}>
            <summary>Quantitative interpretation</summary>
            <div className="explain-grid">
              <div className="explain-metric">
                <span className="muted small">Benchmark</span>
                <strong className="mono">
                  {data.benchmark.status === 'available'
                    ? fmtSignedPct(data.benchmark.return)
                    : '—'}
                </strong>
                <span className="muted small">
                  {data.benchmark.status === 'available'
                    ? `${data.benchmark.ticker ?? data.benchmark.security_id}`
                    : data.benchmark.reason ?? 'not available'}
                </span>
              </div>
              <div className="explain-metric">
                <span className="muted small">Excess (arithmetic)</span>
                <strong className="mono">
                  {data.benchmark.excess_return_arithmetic === undefined
                    ? '—'
                    : fmtSignedPct(data.benchmark.excess_return_arithmetic)}
                </strong>
                <span className="muted small">{data.benchmark.excess_note ?? 'not claimed'}</span>
              </div>
              <div className="explain-metric">
                <span className="muted small">Beta</span>
                <strong className="mono">
                  {data.market_model.beta === undefined ? '—' : fmtNumber(data.market_model.beta, 3)}
                </strong>
                <span className="muted small">
                  {data.market_model.estimation
                    ? `${data.market_model.estimation.sessions} pre-interval session(s)`
                    : data.market_model.reason ?? 'not identified'}
                </span>
              </div>
              <div className="explain-metric">
                <span className="muted small">R²</span>
                <strong className="mono">
                  {data.market_model.r_squared == null ? '—' : fmtNumber(data.market_model.r_squared, 3)}
                </strong>
                <span className="muted small">single-factor fit</span>
              </div>
              <div className="explain-metric">
                <span className="muted small">Market component</span>
                <strong className="mono">
                  {data.market_model.market_component_of_return === undefined
                    ? '—'
                    : fmtSignedPct(data.market_model.market_component_of_return)}
                </strong>
                <span className="muted small">beta × benchmark return</span>
              </div>
              <div className="explain-metric">
                <span className="muted small">Residual</span>
                <strong className="mono">
                  {data.market_model.residual_return_arithmetic === undefined
                    ? '—'
                    : fmtSignedPct(data.market_model.residual_return_arithmetic)}
                </strong>
                <span className="muted small">what the model does not explain</span>
              </div>
            </div>
            {data.market_model.applicability && (
              <ul className="small muted">
                {data.market_model.applicability.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            )}
            {data.price_statistics.overnight_compounded !== null && (
              <p className="small muted">
                Overnight {fmtSignedPct(data.price_statistics.overnight_compounded)} · intraday{' '}
                {fmtSignedPct(data.price_statistics.intraday_compounded)} ·{' '}
                {data.price_statistics.gap_note}
              </p>
            )}
          </details>

          <details className="explain-detail" open={advanced}>
            <summary>Evidence inspector and reproducibility</summary>
            <div className="explain-columns">
              <div>
                <h5>Confirmed observations</h5>
                <ul className="small">
                  {data.observations.map((observation) => (
                    <li key={observation.observation_id}>
                      <span className="mono">{observation.observation_id}</span> —{' '}
                      {observation.statement}{' '}
                      <span className="muted">({observation.derivation})</span>
                    </li>
                  ))}
                </ul>
                <h5>Sources and rights</h5>
                <ul className="small">
                  {data.rights.sources.map((source) => (
                    <li key={source.source_id}>
                      <span className="mono">{source.source_id}</span> · {source.name} ·{' '}
                      {source.licence ?? 'licence not recorded'} ·{' '}
                      <Badge tone={source.redistribution === 'restricted' ? 'warn' : 'accent'}>
                        {source.redistribution}
                      </Badge>
                    </li>
                  ))}
                </ul>
                <p className="small">
                  Export allowed:{' '}
                  <strong>{data.rights.export_allowed ? 'yes' : 'no — restricted source'}</strong>
                </p>
              </div>
              <div>
                <h5>Boundary observations</h5>
                <p className="mono small wrap">
                  start {data.price_statistics.start_observation_id} · end{' '}
                  {data.price_statistics.end_observation_id}
                </p>
                <h5>Reproducibility</h5>
                <p className="mono small wrap">{data.reproducibility.hash}</p>
                <p className="muted small">{data.reproducibility.note}</p>
                <h5>Revision check</h5>
                <p className="small">
                  {data.revision_check.status} · {data.revision_check.amending_filings} amending
                  filing(s) · {data.revision_check.corrected_corporate_actions} corrected action(s)
                </p>
                {data.warnings.length > 0 && (
                  <>
                    <h5>Warnings</h5>
                    <ul className="small muted">
                      {data.warnings.map((warning, index) => (
                        <li key={`${warning.code}-${index}`}>
                          <span className="mono">{warning.code}</span> — {warning.message}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                <h5>Limitations</h5>
                <ul className="small muted">
                  {data.limitations.map((limitation, index) => (
                    <li key={index}>{limitation}</li>
                  ))}
                </ul>
              </div>
            </div>
          </details>

          <div className="explain-actions">
            <button
              className="button secondary"
              onClick={() => downloadReport(data)}
              disabled={!data.rights.export_allowed}
              title={
                data.rights.export_allowed
                  ? 'Download the auditable JSON report'
                  : 'A cited source is restricted, so the resolved values may not be exported'
              }
            >
              Export report
            </button>
            <span className="muted small">
              The exported record contains the selection, statistics, evidence ids, warnings and
              hash — not restricted vendor values.
            </span>
          </div>

          <details className="explain-detail">
            <summary>Compare with another interval</summary>
            <div className="toolbar wrap">
              <label className="inline-field small">
                From
                <input
                  className="field mono"
                  type="date"
                  defaultValue=""
                  id="compare-start"
                />
              </label>
              <label className="inline-field small">
                To
                <input className="field mono" type="date" defaultValue="" id="compare-end" />
              </label>
              <button
                className="button secondary"
                onClick={() => {
                  const start = (document.getElementById('compare-start') as HTMLInputElement | null)?.value
                  const end = (document.getElementById('compare-end') as HTMLInputElement | null)?.value
                  if (start && end) void compare(start, end)
                }}
              >
                Compare
              </button>
            </div>
            {comparison?.loading && <Loading label="Reconstructing comparison interval" />}
            {comparison?.error && <p className="small" role="alert">{comparison.error}</p>}
            {comparison?.report && (
              <table className="mini-table">
                <thead>
                  <tr>
                    <th>Interval</th>
                    <th className="numeric">Return</th>
                    <th className="numeric">Sessions</th>
                    <th className="numeric">Max drawdown</th>
                    <th className="numeric">Events</th>
                    <th>Top explanation</th>
                  </tr>
                </thead>
                <tbody>
                  {[data, comparison.report].map((row) => (
                    <tr key={`${row.selection.start_session}-${row.selection.end_session}`}>
                      <td className="mono small">
                        {row.selection.start_session} → {row.selection.end_session}
                      </td>
                      <td className={`numeric mono ${toneForNumber(row.price_statistics.interval_return)}`}>
                        {fmtSignedPct(row.price_statistics.interval_return)}
                      </td>
                      <td className="numeric mono">{row.price_statistics.sessions}</td>
                      <td className="numeric mono">{fmtSignedPct(row.price_statistics.max_drawdown)}</td>
                      <td className="numeric mono">{row.events.in_window_count}</td>
                      <td className="small">{row.hypotheses[0]?.statement ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </details>
        </>
      )}
    </section>
  )
}

function EventRow({ event }: { event: PriceExplanationEvent }) {
  const label =
    event.kind === 'corporate_action'
      ? event.title
      : `${event.form_type ?? event.kind} · ${event.form_label ?? 'SEC filing'}`
  return (
    <li>
      <div className="event-head">
        <span className="mono small">{event.date}</span>
        <Badge tone={event.relation === 'in_window' ? 'accent' : 'neutral'}>{event.relation}</Badge>
        {event.is_amendment && <Badge tone="warn">amendment</Badge>}
      </div>
      <div>{label}</div>
      <div className="muted small">
        {event.accession_number ? (
          <span className="mono">{event.accession_number}</span>
        ) : (
          <span className="mono">{event.event_id}</span>
        )}
        {event.availability_time && <> · public {fmtDateTime(event.availability_time)}</>}
        {event.known_at_range_end === false && <> · not known at the interval's end</>}
      </div>
    </li>
  )
}
