import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useAsync } from '../state'
import type {
  PriceExplanation,
  PriceExplanationBasis,
  PriceExplanationDocument,
  PriceExplanationEvent,
  PriceExplanationMode,
  PriceExplanationRequest,
  PriceExplanationTemporal,
  ReopenedPriceInvestigation,
  SavedPriceInvestigationSummary,
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

function downloadJson(payload: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function downloadReport(report: PriceExplanation) {
  const ticker = report.selection.ticker ?? report.selection.security_id
  downloadJson(
    report,
    `atlas-price-explanation-${ticker}-${report.selection.start_session}-${report.selection.end_session}.json`,
  )
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
  const [saved, setSaved] = useState<{
    object_id: string
    version: string
    content_hash: string
    reproducibility_hash: string
    as_of: string
    temporal?: PriceExplanationTemporal
  } | null>(null)
  const [impact, setImpact] = useState<{
    status: string
    comparison_kind?: string
    categories: string[]
    note: string
    computed_at?: string
  } | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedList, setSavedList] = useState<SavedPriceInvestigationSummary[]>([])
  const [reopened, setReopened] = useState<ReopenedPriceInvestigation | null>(null)
  const [reopenError, setReopenError] = useState<string | null>(null)

  useEffect(() => {
    setCutoff((current) => (current < selection.end ? selection.end : current))
  }, [selection.end])

  useEffect(() => {
    let cancelled = false
    api
      .priceInvestigations(securityId)
      .then((result) => {
        if (!cancelled) setSavedList(result.items)
      })
      .catch(() => {
        /* a missing saved-work list must not block a new investigation */
      })
    return () => {
      cancelled = true
    }
  }, [securityId])

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

  async function saveInvestigation() {
    setSaving(true)
    setSaveError(null)
    setImpact(null)
    try {
      const stored = await api.savePriceInvestigation(securityId, {
        ...request,
        version: '1.0.0',
      })
      setSaved({
        object_id: stored.object_id,
        version: stored.version,
        content_hash: stored.content_hash,
        reproducibility_hash: stored.reproducibility_hash,
        as_of: stored.as_of,
        temporal: stored.temporal,
      })
      const listed = await api.priceInvestigations(securityId)
      setSavedList(listed.items)
    } catch (caught) {
      setSaveError((caught as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function checkForChanges(objectId: string) {
    setSaveError(null)
    try {
      setImpact(await api.investigationImpact(objectId))
    } catch (caught) {
      setSaveError((caught as Error).message)
    }
  }

  async function reopenInvestigation(objectId: string) {
    setReopenError(null)
    setSaveError(null)
    try {
      setReopened(await api.priceInvestigation(objectId))
    } catch (caught) {
      setReopened(null)
      setReopenError((caught as Error).message)
    }
  }

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
          {mode === 'historical_reconstruction' && (
            <p className="small">
              <Badge tone="warn">price vintage unverified</Badge>{' '}
              <span className="muted">
                sessions are filtered by date, not by the provider's publication vintage; Atlas
                cannot prove these prices were published by the cutoff.
              </span>
            </p>
          )}
          {data?.selection.return_convention === 'single_session_close_to_close' && (
            <p className="muted small">
              A one-candle selection measures the move from the previous eligible session's close.
            </p>
          )}
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
                      {hypothesis.relevance.citations.length > 0 && (
                        <>
                          <h6>Cited document spans</h6>
                          <ul className="small">
                            {hypothesis.relevance.citations.map((citation) => (
                              <li key={`${citation.document_id}-${citation.unit_id}`}>
                                <span className="mono">
                                  {citation.accession} · {citation.section_path} · chars{' '}
                                  {citation.char_start}–{citation.char_end}
                                </span>
                                {citation.excerpt ? (
                                  <blockquote className="small">“{citation.excerpt}”</blockquote>
                                ) : (
                                  <span className="muted small">
                                    {' '}
                                    {citation.excerpt_withheld ?? 'no text quoted'}
                                  </span>
                                )}
                                {citation.source_url && (
                                  <a
                                    className="small"
                                    href={citation.source_url}
                                    target="_blank"
                                    rel="noreferrer noopener"
                                  >
                                    Open original SEC document
                                  </a>
                                )}
                              </li>
                            ))}
                          </ul>
                        </>
                      )}
                      {hypothesis.relevance.counterevidence.length > 0 && (
                        <>
                          <h6>Counterevidence</h6>
                          <ul className="small muted">
                            {hypothesis.relevance.counterevidence.map((entry, index) => (
                              <li key={index}>
                                {String((entry as { statement?: string }).statement ?? '')}
                              </li>
                            ))}
                          </ul>
                        </>
                      )}
                      {hypothesis.relevance.alternatives.length > 0 && (
                        <>
                          <h6>Alternative explanations</h6>
                          <ul className="small muted">
                            {hypothesis.relevance.alternatives.map((alternative) => (
                              <li key={alternative.kind}>{alternative.statement}</li>
                            ))}
                          </ul>
                        </>
                      )}
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
                <span className="muted small">Expected return (compounded)</span>
                <strong className="mono">
                  {data.market_model.expected_return_compounded === undefined
                    ? '—'
                    : fmtSignedPct(data.market_model.expected_return_compounded)}
                </strong>
                <span className="muted small">alpha + beta × benchmark, compounded daily</span>
              </div>
              <div className="explain-metric">
                <span className="muted small">Abnormal return</span>
                <strong className="mono">
                  {data.market_model.abnormal_return_difference === undefined
                    ? '—'
                    : fmtSignedPct(data.market_model.abnormal_return_difference)}
                </strong>
                <span className="muted small">
                  return minus compounded expected return — what the model does not explain
                </span>
              </div>
              {data.market_model.first_order_approximation && (
                <div className="explain-metric">
                  <span className="muted small">First-order check</span>
                  <strong className="mono">
                    {fmtSignedPct(
                      data.market_model.first_order_approximation.beta_times_benchmark,
                    )}
                  </strong>
                  <span className="muted small">
                    beta × benchmark return; an approximation, not the abnormal return
                  </span>
                </div>
              )}
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
                  <strong>
                    {data.rights.export_allowed
                      ? 'yes'
                      : data.rights.unregistered_sources?.length
                        ? 'no — unregistered source'
                        : 'no — restricted source'}
                  </strong>
                </p>
                {!data.rights.export_allowed && (data.rights.reasons?.length ?? 0) > 0 && (
                  <ul className="small muted">
                    {data.rights.reasons?.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <h5>Boundary observations</h5>
                <p className="mono small wrap">
                  start {data.price_statistics.start_observation_id} · end{' '}
                  {data.price_statistics.end_observation_id}
                </p>
                {data.price_statistics.return_convention === 'single_session_close_to_close' && (
                  <p className="muted small">
                    The start boundary is the previous eligible session, not the selected candle.
                  </p>
                )}
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
              className="button"
              onClick={() => void saveInvestigation()}
              disabled={saving || !data.reproducibility.hash}
              title="Save an immutable, versioned research investigation on the UROS contract"
            >
              {saving ? 'Saving…' : 'Save investigation'}
            </button>
            {saved && (
              <div className="small saved-summary">
                <span>
                  <span className="mono">{saved.object_id}</span> v{saved.version} ·{' '}
                  <span className="mono wrap">{saved.content_hash.slice(0, 12)}…</span> · saved
                  as of <strong data-testid="saved-as-of">{saved.as_of}</strong>{' '}
                  {saved.temporal?.retrospective
                    ? '(retrospective run)'
                    : '(historical cutoff)'}
                </span>
                <button
                  className="button secondary"
                  onClick={() => void checkForChanges(saved.object_id)}
                >
                  Check for changes
                </button>
              </div>
            )}
            {impact && (
              <div className="small muted saved-summary" data-testid="impact-status">
                {impact.status}
                {impact.comparison_kind ? ` (${impact.comparison_kind})` : ''}
                {impact.categories.length > 0 ? `: ${impact.categories.join(', ')}` : ''} —{' '}
                {impact.note}
              </div>
            )}
            {saveError && (
              <span className="small" role="alert">
                {saveError}
              </span>
            )}
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

          <details className="explain-detail" data-testid="saved-investigations">
            <summary>Saved investigations ({savedList.length})</summary>
            {savedList.length === 0 ? (
              <p className="muted small">
                No saved investigation for this security yet. Saving stores an immutable,
                versioned object; it is not overwritten by later data.
              </p>
            ) : (
              <ul className="saved-investigation-list small">
                {savedList.map((item) => (
                  <li key={item.object_id}>
                    <div>
                      <strong>{item.name}</strong> v{item.version} ·{' '}
                      <span className="mono wrap">{item.object_id}</span>
                    </div>
                    <div className="muted">
                      observed {item.start_session ?? '—'} → {item.end_session ?? '—'} · as of{' '}
                      {item.as_of ?? '—'}
                    </div>
                    <div className="toolbar wrap">
                      <button
                        className="button secondary"
                        data-testid="reopen-investigation"
                        onClick={() => void reopenInvestigation(item.object_id)}
                      >
                        Reopen saved work
                      </button>
                      <button
                        className="button secondary"
                        onClick={() => void checkForChanges(item.object_id)}
                      >
                        Check for changes
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {reopenError && (
              <p className="small" role="alert" data-testid="reopen-error">
                {reopenError}
              </p>
            )}
            {reopened && (
              <div className="saved-snapshot" data-testid="saved-snapshot">
                <h5>
                  {reopened.name} v{reopened.version}
                </h5>
                <p className="small">
                  Reopened stored object <span className="mono">{reopened.object_id}</span> · saved
                  as of <strong>{reopened.as_of}</strong>
                </p>
                <p className="small">
                  <strong>
                    {reopened.temporal.retrospective
                      ? 'Retrospective investigation'
                      : 'Historical reconstruction'}
                  </strong>
                </p>
                <p className="small muted">{reopened.temporal.as_of_basis}</p>
                <p className="small muted">
                  Observation period {reopened.document.spec.interval.start_session} →{' '}
                  {reopened.document.spec.interval.end_session} ·{' '}
                  {reopened.document.spec.statistics.sessions} session(s) ·{' '}
                  {fmtSignedPct(reopened.document.spec.statistics.interval_return)} ·{' '}
                  {reopened.document.spec.hypotheses.length} hypothesis(es)
                </p>
                <p className="small muted">
                  Knowledge cutoff {reopened.temporal.public_knowledge_cutoff.instant} (
                  {reopened.temporal.public_knowledge_cutoff.basis}) · repro hash{' '}
                  <span className="mono wrap">
                    {reopened.document.spec.reproducibility.hash.slice(0, 16)}…
                  </span>
                </p>
                <button
                  className="button secondary"
                  onClick={() =>
                    downloadJson(
                      reopened.document,
                      `atlas-saved-investigation-${reopened.object_id}.json`,
                    )
                  }
                >
                  Download saved JSON
                </button>
              </div>
            )}
          </details>

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

function DocumentEvidence({ document }: { document: PriceExplanationDocument }) {
  const openable = document.source_locator?.url
  return (
    <div className="document-evidence small">
      <div className="event-head">
        <Badge tone={document.status === 'resolved' ? 'accent' : 'warn'}>
          {document.status.replace(/_/g, ' ')}
        </Badge>
        {document.is_amendment && <Badge tone="warn">amends {document.amends_accession}</Badge>}
      </div>
      <div className="muted">
        Filed {document.filed_date} · version {document.filing_version} · document{' '}
        {document.primary_document ?? 'not recorded'}
      </div>
      {document.sha256 && (
        <div className="mono wrap">sha256 {document.sha256}</div>
      )}
      {openable ? (
        <a
          href={openable}
          target="_blank"
          rel="noreferrer noopener"
          data-testid="document-link"
        >
          Open original SEC document
        </a>
      ) : (
        <span className="muted">{document.source_locator?.reason ?? 'original locator unavailable'}</span>
      )}
      {document.items.length > 0 && (
        <div>
          Disclosed items:{' '}
          {document.items.map((item) => (
            <span key={item.item} className="mono">
              {item.item} {item.label}{' '}
            </span>
          ))}
        </div>
      )}
      {document.passages.length > 0 && (
        <details>
          <summary>Supporting passages ({document.passages.length})</summary>
          <ul>
            {document.passages.map((passage) => (
              <li key={passage.unit_id}>
                <div className="mono">
                  {passage.section_path} · chars {passage.char_start}–{passage.char_end} · span{' '}
                  {passage.sha256.slice(0, 12)}…
                </div>
                <div className="mono small muted" data-testid="passage-citation">
                  {passage.citation}
                </div>
                {passage.excerpt ? (
                  <blockquote>“{passage.excerpt}”</blockquote>
                ) : (
                  <span className="muted">{passage.excerpt_withheld ?? 'text not quoted'}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {document.reason && <p className="muted">{document.reason}</p>}
    </div>
  )
}

function EventRow({ event }: { event: PriceExplanationEvent }) {
  const label =
    event.kind === 'corporate_action'
      ? event.title
      : `${event.form_type ?? event.kind} · ${event.form_label ?? 'SEC filing'}`
  const filed = event.filed_date ?? event.date
  const published = event.availability_time
  return (
    <li>
      <div className="event-head">
        <span className="mono small">{published ?? filed}</span>
        <Badge
          tone={
            event.relation === 'in_window'
              ? 'accent'
              : event.relation === 'subsequent_to_price_window'
                ? 'warn'
                : 'neutral'
          }
        >
          {event.explanatory_eligible === false && event.relation === 'subsequent_to_price_window'
            ? 'after final close'
            : event.relation.replace(/_/g, ' ')}
        </Badge>
        {event.is_amendment && <Badge tone="warn">amendment</Badge>}
        {event.duplicate_document_of && <Badge tone="neutral">duplicate document</Badge>}
      </div>
      <div>{label}</div>
      <div className="muted small">
        {event.accession_number ? (
          <span className="mono">{event.accession_number}</span>
        ) : (
          <span className="mono">{event.event_id}</span>
        )}
        {published && (
          <>
            {' '}
            · public {fmtDateTime(published)}
            {event.availability_precision === 'date' ? ' (end of day, date precision)' : ''}
          </>
        )}
        {filed !== event.date && <> · filed {fmtDate(filed)}</>}
        {event.publication?.local_time && (
          <> · local {event.publication.local_time} ({event.publication.timezone})</>
        )}
        {event.publication?.phase && event.publication.phase !== 'unknown' && (
          <> · {event.publication.phase.replace(/_/g, ' ')}</>
        )}
        {event.publication?.tradable_session && (
          <> · first tradable session {event.publication.tradable_session}</>
        )}
        {event.known_at_range_end === false && <> · not known at the interval's end</>}
        {event.supersedes_event_id && <> · keeps original {event.supersedes_event_id}</>}
      </div>
      {event.explanatory_eligibility && event.explanatory_eligibility.eligible === false && (
        <div className="small muted" data-testid="ineligible-reason">
          Not a candidate explanation: {event.explanatory_eligibility.reason}
        </div>
      )}
      {event.document && <DocumentEvidence document={event.document} />}
    </li>
  )
}
