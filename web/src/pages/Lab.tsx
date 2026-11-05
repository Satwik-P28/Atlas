import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Badge } from '../components/ui'

type Row = Record<string, any>

const pct = (value: unknown) =>
  value === null || value === undefined ? '—' : `${(Number(value) * 100).toFixed(2)}%`
const usd = (value: unknown) =>
  value === null || value === undefined
    ? '—'
    : `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
const num = (value: unknown, digits = 2) =>
  value === null || value === undefined ? '—' : Number(value).toFixed(digits)

function downsample(points: Row[], limit = 420): Row[] {
  if (points.length <= limit) return points
  const result: Row[] = []
  for (let i = 0; i < limit; i += 1) {
    result.push(points[Math.round((i * (points.length - 1)) / (limit - 1))])
  }
  return result
}

function normalise(curve: Row[]): Array<{ date: string; value: number }> {
  if (!curve.length) return []
  const base = Number(curve[0].equity)
  return downsample(curve).map((point) => ({
    date: String(point.date),
    value: base ? (Number(point.equity) / base) * 100 : 100,
  }))
}

function drawdown(curve: Row[]): Array<{ date: string; value: number }> {
  let peak = 0
  return downsample(curve).map((point) => {
    const equity = Number(point.equity)
    peak = Math.max(peak, equity)
    return { date: String(point.date), value: peak ? equity / peak - 1 : 0 }
  })
}

function CurveChart({
  strategy,
  benchmark,
  label,
}: {
  strategy: Row[]
  benchmark: Row[]
  label: string
}) {
  const strategyPoints = useMemo(() => normalise(strategy), [strategy])
  const benchmarkPoints = useMemo(() => normalise(benchmark), [benchmark])
  const all = [...strategyPoints, ...benchmarkPoints]
  if (all.length < 2) return <div className="state-block">No marked sessions to plot.</div>
  const width = 900
  const height = 260
  const padX = 18
  const padY = 18
  const values = all.map((point) => point.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const pathFor = (points: Array<{ value: number }>) =>
    points
      .map((point, index) => {
        const x = padX + (index / Math.max(1, points.length - 1)) * (width - padX * 2)
        const y = height - padY - ((point.value - min) / range) * (height - padY * 2)
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
      })
      .join(' ')
  const firstDate = strategyPoints[0]?.date ?? ''
  const lastDate = strategyPoints[strategyPoints.length - 1]?.date ?? ''
  return (
    <div className="lab-chart">
      <div className="chart-legend">
        <span><span className="lab-swatch lab-swatch-accent" /> Strategy</span>
        <span><span className="lab-swatch lab-swatch-muted" /> Buy &amp; hold</span>
        <span className="muted small">Normalised to 100 · {label}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Strategy and benchmark equity curve">
        <line x1={padX} y1={height - padY} x2={width - padX} y2={height - padY} className="lab-axis" />
        <line x1={padX} y1={padY} x2={padX} y2={height - padY} className="lab-axis" />
        <path d={pathFor(benchmarkPoints)} className="lab-line lab-line-muted" />
        <path d={pathFor(strategyPoints)} className="lab-line lab-line-accent" />
      </svg>
      <div className="chart-facts">
        <span className="mono small">{firstDate}</span>
        <span className="muted small">→</span>
        <span className="mono small">{lastDate}</span>
        <span className="muted small">indexed total portfolio value</span>
      </div>
    </div>
  )
}

function DrawdownChart({ curve }: { curve: Row[] }) {
  const points = useMemo(() => drawdown(curve), [curve])
  if (points.length < 2) return null
  const width = 900
  const height = 120
  const pad = 10
  const worst = Math.min(...points.map((point) => point.value), -0.0001)
  const path = points
    .map((point, index) => {
      const x = pad + (index / (points.length - 1)) * (width - pad * 2)
      const y = pad + (Math.abs(point.value) / Math.abs(worst)) * (height - pad * 2)
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
  return (
    <div className="lab-drawdown">
      <div className="chart-legend">
        <span><span className="lab-swatch lab-swatch-negative" /> Strategy drawdown</span>
        <span className="muted small">worst {pct(worst)}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Strategy drawdown curve">
        <path d={`${path} L${width - pad},${pad} L${pad},${pad} Z`} className="lab-area" />
        <path d={path} className="lab-line lab-line-negative" />
      </svg>
    </div>
  )
}

function Metric({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: string }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${tone ?? ''}`}>{value}</div>
      {detail && <div className="muted small">{detail}</div>}
    </div>
  )
}

export default function Lab() {
  const [catalog, setCatalog] = useState<Row | null>(null)
  const [runs, setRuns] = useState<Row[]>([])
  const [experiments, setExperiments] = useState<Row[]>([])
  const [instrumentId, setInstrumentId] = useState('')
  const [templateKey, setTemplateKey] = useState('buy_hold')
  const [start, setStart] = useState('2015-01-02')
  const [end, setEnd] = useState('2026-11-03')
  const [capital, setCapital] = useState('100000')
  const [commission, setCommission] = useState('2')
  const [slippage, setSlippage] = useState('5')
  const [fast, setFast] = useState('20')
  const [slow, setSlow] = useState('100')
  const [result, setResult] = useState<Row | null>(null)
  const [capsule, setCapsule] = useState<Row | null>(null)
  const [replay, setReplay] = useState<Row | null>(null)
  const [compare, setCompare] = useState<Row[] | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const instruments = (catalog?.universe ?? []) as Row[]
  const templates = (catalog?.templates ?? []) as Row[]
  const instrument = instruments.find((item) => item.security_id === instrumentId) ?? instruments[0]
  const template = templates.find((item) => item.key === templateKey) ?? templates[0]

  useEffect(() => {
    void refreshCatalog()
    void refreshHistory()
  }, [])

  useEffect(() => {
    if (!instrument) return
    if (!instrumentId) setInstrumentId(instrument.security_id)
    const first = String(instrument.first_bar ?? '').slice(0, 10)
    const last = String(instrument.last_bar ?? '').slice(0, 10)
    if (last) setEnd((current) => (current === '2026-11-03' ? last : current))
    if (first && first > start) setStart(first)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instrument?.security_id])

  async function refreshCatalog() {
    try {
      setCatalog(await api.quantCatalog())
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  async function refreshHistory() {
    try {
      const [runPayload, experimentPayload] = await Promise.all([api.quantRuns(), api.quantExperiments()])
      setRuns(runPayload.items)
      setExperiments(experimentPayload.items)
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  function chooseTemplate(key: string) {
    setTemplateKey(key)
    if (key === 'sma_cross') {
      setFast('20')
      setSlow('100')
    } else if (key === 'momentum') {
      setFast('60')
    }
  }

  function buildSpec() {
    if (!template || !instrument) throw new Error('Catalog is not loaded')
    const signal = JSON.parse(JSON.stringify(template.signal))
    if (signal.kind === 'sma_cross') {
      signal.fast = Number(fast)
      signal.slow = Number(slow)
    } else if (signal.kind === 'momentum') {
      signal.fast = Number(fast)
    }
    const parameter = signal.kind === 'sma_cross'
      ? `${signal.fast}/${signal.slow}`
      : signal.kind === 'momentum' ? String(signal.fast) : signal.kind
    const name = `${template.label} · ${instrument.ticker ?? instrument.security_id.slice(-6)} · ${parameter} · ${commission}/${slippage}bps · ${capital}`
    return {
      schema_version: 'atlas.strategy.v1',
      name,
      version: '1.0.0',
      description: template.description,
      universe: { instruments: [{ security_id: instrument.security_id, mic: instrument.mic }] },
      features: template.features,
      signal,
      decision_frequency: 'daily',
      rebalance: 'daily',
      execution: { signal_at: 'close', fill_at: 'next_open', commission_bps: Number(commission), slippage_bps: Number(slippage) },
      benchmark: { kind: 'buy_hold' },
      initial_capital: Number(capital),
      constraints: { long_only: true, max_position: 1 },
      risk_free_rate: 0.02,
    }
  }

  async function run() {
    setLoading(true)
    setError(null)
    setMessage(null)
    setCapsule(null)
    setReplay(null)
    setCompare(null)
    try {
      const spec = buildSpec()
      const payload = await api.quantBacktest({
        spec,
        as_of: end,
        start,
        end,
        initial_capital: Number(capital),
        commission_bps: Number(commission),
        slippage_bps: Number(slippage),
        hypothesis: `${template?.label ?? 'Strategy'} on ${instrument?.ticker ?? 'the selected instrument'} after costs.`,
        experiment_name: `${template?.label ?? 'Strategy'} ${instrument?.ticker ?? ''} ${new Date().toISOString().slice(0, 19)}`,
        persist: true,
      })
      setResult(payload)
      setMessage(`Experiment saved · ${payload.experiment_object_id ?? 'not persisted'}`)
      await refreshHistory()
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function loadRun(runId: string) {
    setError(null)
    try {
      const payload = await api.quantRun(runId)
      setResult(payload)
      setMessage(`Reopened ${runId}`)
      setCapsule(null)
      setReplay(null)
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  async function loadExperiment(objectId: string) {
    setError(null)
    try {
      const object = await api.researchObject(objectId)
      const runId = object.document?.spec?.run_id
      if (!runId) throw new Error('Experiment does not reference a run')
      await loadRun(runId)
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  async function forkExperiment() {
    if (!result?.experiment_object_id) return
    setError(null)
    try {
      const name = `${result.strategy_name ?? 'Experiment'} fork ${new Date().toISOString().slice(0, 19)}`
      const forked = await api.forkResearchObject(result.experiment_object_id, name)
      setMessage(`Forked experiment ${forked.object_id}`)
      await refreshHistory()
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  async function openCapsule() {
    if (!result?.run_id) return
    setError(null)
    try {
      setCapsule(await api.quantCapsule(result.run_id))
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  async function replayRun() {
    if (!result?.run_id) return
    setError(null)
    try {
      setReplay(await api.quantReplay(result.run_id))
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  async function exportExperiment() {
    if (!result?.experiment_object_id) return
    setError(null)
    try {
      const manifest = await api.exportResearchObject(result.experiment_object_id)
      const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${result.experiment_object_id}-research-manifest.json`
      anchor.click()
      URL.revokeObjectURL(url)
      setMessage('Exported the complete experiment manifest.')
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  async function compareLatest() {
    setError(null)
    try {
      const ids = runs.slice(0, 2).map((item) => item.run_id)
      if (ids.length < 2) throw new Error('Run at least two experiments first')
      const [left, right] = await Promise.all(ids.map((id) => api.quantRun(id)))
      setCompare([left, right])
    } catch (caught) {
      setError((caught as Error).message)
    }
  }

  const metrics = result?.metrics ?? {}
  const benchmark = result?.benchmark?.metrics ?? {}
  const reconciliation = result?.reconciliation ?? {}
  const credibility = result?.credibility ?? {}
  const strategyReturn = metrics.total_return as number | null
  const benchmarkReturn = benchmark.total_return as number | null
  const strategyTone = strategyReturn == null ? '' : strategyReturn >= 0 ? 'positive' : 'negative'
  const excessTone = metrics.excess_return == null ? '' : metrics.excess_return >= 0 ? 'positive' : 'negative'

  return (
    <div className="page">
      <div className="section-header">
        <div>
          <div className="eyebrow">Quant Lab · Alpha Foundry</div>
          <h1>Research, not a performance chart</h1>
          <p className="section-detail">
            Signals use observations through the session close and fill at the next available open.
            Every experiment keeps its strategy, accounting, costs, limitations and replay fingerprint.
          </p>
        </div>
        <div className="section-actions">
          <Link className="button" to="/lab/institutional">Risk &amp; pricing</Link>
          <Badge tone="accent">Next-open fills</Badge>
          <Badge tone="neutral">Long only</Badge>
          <Badge tone="warn">No live trading</Badge>
        </div>
      </div>

      <section className="card lab-controls">
        <div className="lab-field">
          <label htmlFor="lab-instrument">Instrument</label>
          <select id="lab-instrument" className="field" value={instrument?.security_id ?? ''} onChange={(event) => setInstrumentId(event.target.value)}>
            {instruments.map((item) => (
              <option key={item.security_id} value={item.security_id}>
                {item.ticker ?? item.security_id.slice(-6)} · {item.legal_name} · {item.sessions.toLocaleString()} bars
              </option>
            ))}
          </select>
        </div>
        <div className="lab-field">
          <label htmlFor="lab-template">Research strategy</label>
          <select id="lab-template" className="field" value={template?.key ?? ''} onChange={(event) => chooseTemplate(event.target.value)}>
            {templates.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
          </select>
        </div>
        <div className="lab-field">
          <label htmlFor="lab-start">Start</label>
          <input id="lab-start" className="field mono" type="date" value={start} onChange={(event) => setStart(event.target.value)} />
        </div>
        <div className="lab-field">
          <label htmlFor="lab-end">Information cutoff / end</label>
          <input id="lab-end" className="field mono" type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
        </div>
        <div className="lab-field">
          <label htmlFor="lab-capital">Initial capital</label>
          <input id="lab-capital" className="field mono" type="number" min={1} value={capital} onChange={(event) => setCapital(event.target.value)} />
        </div>
        <div className="lab-field">
          <label htmlFor="lab-commission">Commission (bps)</label>
          <input id="lab-commission" className="field mono" type="number" min={0} value={commission} onChange={(event) => setCommission(event.target.value)} />
        </div>
        <div className="lab-field">
          <label htmlFor="lab-slippage">Slippage (bps)</label>
          <input id="lab-slippage" className="field mono" type="number" min={0} value={slippage} onChange={(event) => setSlippage(event.target.value)} />
        </div>
        {(template?.key === 'sma_cross' || template?.key === 'momentum') && (
          <>
            <div className="lab-field">
              <label htmlFor="lab-fast">{template.key === 'sma_cross' ? 'Fast window' : 'Lookback'}</label>
              <input id="lab-fast" className="field mono" type="number" min={2} value={fast} onChange={(event) => setFast(event.target.value)} />
            </div>
            {template.key === 'sma_cross' && (
              <div className="lab-field">
                <label htmlFor="lab-slow">Slow window</label>
                <input id="lab-slow" className="field mono" type="number" min={3} value={slow} onChange={(event) => setSlow(event.target.value)} />
              </div>
            )}
          </>
        )}
        <div className="lab-run-action">
          <button className="button button-primary" onClick={run} disabled={loading || !catalog}>
            {loading ? 'Running simulation…' : 'Run research'}
          </button>
        </div>
      </section>

      {template && (
        <div className="banner banner-info">
          <strong>{template.label}.</strong> {template.description} The model is a declaration; Atlas evaluates only typed operators and next-open fills.
        </div>
      )}
      {error && <div className="banner banner-warn error-text" data-testid="lab-error">{error}</div>}
      {message && <div className="banner banner-info" data-testid="lab-message">{message}</div>}

      {!result && !loading && (
        <div className="state-block">
          <div>
            <div className="state-title">Choose a hypothesis and run it.</div>
            <div className="muted small">The first run on IBM uses real vendor OHLCV observations, commissions, slippage, splits and cash dividends.</div>
          </div>
          <span className="mono muted small">signal → close · fill → next open</span>
        </div>
      )}

      {result && (
        <>
          <div className="metric-grid">
            <Metric label="Strategy return" value={pct(strategyReturn)} detail={`${metrics.sessions ?? 0} marked sessions`} tone={strategyTone} />
            <Metric label="Buy & hold" value={pct(benchmarkReturn)} detail="same costs, same sessions" />
            <Metric label="Excess return" value={pct(metrics.excess_return)} detail="before statistical significance" tone={excessTone} />
            <Metric label="Sharpe" value={num(metrics.sharpe, 2)} detail="2% risk-free · daily returns" />
            <Metric label="Max drawdown" value={pct(metrics.max_drawdown)} detail={`${metrics.max_drawdown_duration_sessions ?? 0} sessions`} tone="negative" />
            <Metric label="Costs" value={usd(metrics.transaction_costs)} detail="commission + modelled slippage" />
            <Metric label="Turnover" value={num(metrics.turnover, 2)} detail="notional / average equity" />
            <Metric label="Ending value" value={usd(metrics.end_equity)} detail={`initial ${usd(metrics.start_equity)}`} />
          </div>

          <div className="split-2">
            <section className="card">
              <div className="section-header">
                <div>
                  <div className="eyebrow">Equity</div>
                  <h2>Strategy vs. buy &amp; hold</h2>
                </div>
                <span className="mono muted small" data-testid="lab-run-id">{result.run_id}</span>
              </div>
              <CurveChart strategy={result.equity_curve ?? []} benchmark={result.benchmark_curve ?? []} label={`${result.security?.security_id?.slice(-6)} · ${result.period?.start} → ${result.period?.end}`} />
              <DrawdownChart curve={result.equity_curve ?? []} />
            </section>
            <section className="card">
              <div className="eyebrow">Accounting reconciliation</div>
              <h2>{reconciliation.reconciled ? 'Every cash flow accounted for' : 'Reconciliation failed'}</h2>
              <table className="mini-table lab-recon">
                <tbody>
                  <tr><th>Beginning cash</th><td className="mono numeric">{usd(reconciliation.beginning_cash)}</td></tr>
                  <tr><th>Trade cash flows</th><td className="mono numeric">{usd(reconciliation.trade_cash_flows)}</td></tr>
                  <tr><th>Dividend income</th><td className="mono numeric">{usd(reconciliation.dividend_income)}</td></tr>
                  <tr><th>Ending cash</th><td className="mono numeric">{usd(reconciliation.ending_cash)}</td></tr>
                  <tr><th>Holdings value</th><td className="mono numeric">{usd(reconciliation.holdings_market_value)}</td></tr>
                  <tr><th>Total portfolio</th><td className="mono numeric">{usd(reconciliation.total_portfolio_value)}</td></tr>
                  <tr><th>Commission / slippage</th><td className="mono numeric">{usd(reconciliation.commissions)} / {usd(reconciliation.slippage_costs ?? reconciliation.slippage_cost)}</td></tr>
                </tbody>
              </table>
              <p className="notice small">{reconciliation.cash_identity}. Difference: {usd(reconciliation.cash_reconciled)}.</p>
            </section>
          </div>

          <div className="split-2">
            <section className="card">
              <div className="eyebrow">Research Credibility Report</div>
              <h2>Interesting result, not yet a validated advantage</h2>
              <div className="lab-credibility">
                <div><span className="muted">Validation</span><strong>{String(credibility.validation?.method ?? 'in_sample_only').replaceAll('_', ' ')}</strong></div>
                <div><span className="muted">Out of sample</span><strong>{credibility.validation?.out_of_sample ? 'Yes' : 'No'}</strong></div>
                <div><span className="muted">Parameter trials</span><strong>{credibility.validation?.parameter_grid_trials ?? 1}</strong></div>
                <div><span className="muted">Replay fingerprint</span><strong className="mono break">{String(credibility.result_fingerprint ?? '').slice(0, 16)}…</strong></div>
              </div>
              <ul className="lab-list">
                {(credibility.limitations ?? []).map((item: string) => <li key={item}>{item}</li>)}
              </ul>
              {Array.isArray(credibility.warnings) && credibility.warnings.length > 0 && (
                <div className="banner banner-warn small">{credibility.warnings.join(' · ')}</div>
              )}
            </section>
            <section className="card">
              <div className="eyebrow">Time Capsule</div>
              <h2>Replay the information set</h2>
              <div className="toolbar wrap">
                <button className="button" onClick={openCapsule}>Inspect capsule</button>
                <button className="button" onClick={replayRun}>Replay run</button>
                <button className="button" onClick={forkExperiment} disabled={!result.experiment_object_id}>Fork experiment</button>
                <button className="button" onClick={exportExperiment} disabled={!result.experiment_object_id}>Export experiment</button>
                <button className="button" onClick={compareLatest} disabled={runs.length < 2}>Compare latest two</button>
              </div>
              {capsule && (
                <div className="lab-capsule" data-testid="lab-capsule">
                  <div><span className="muted">Reproducibility</span><Badge tone={capsule.reproducibility?.fully_reproducible ? 'positive' : 'warn'}>{capsule.reproducibility?.status}</Badge></div>
                  <div><span className="muted">Source archive</span><strong>{capsule.source_archives?.archived_sources?.length ?? 0} source(s) archived</strong></div>
                  <div><span className="muted">Bars</span><strong>{capsule.bars?.reduce((total: number, row: Row) => total + Number(row.rows || 0), 0)?.toLocaleString()}</strong></div>
                  <p className="notice small">{capsule.reproducibility?.note}</p>
                </div>
              )}
              {replay && (
                <div className={`banner ${replay.reproduced ? 'banner-info' : 'banner-warn'} small`} data-testid="lab-replay">
                  {replay.reproduced ? 'Replay fingerprint matched exactly.' : 'Replay differed from the stored run.'}
                  {' '}Original {usd(replay.original_end_equity)} · replay {usd(replay.replay_end_equity)}.
                </div>
              )}
            </section>
          </div>

          {compare && (
            <section className="card">
              <div className="eyebrow">Experiment comparison</div>
              <h2>Same accounting, different hypothesis</h2>
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Run</th><th>Strategy</th><th>Return</th><th>Excess</th><th>Sharpe</th><th>Max drawdown</th><th>Costs</th></tr></thead>
                  <tbody>
                    {compare.map((run: Row) => (
                      <tr key={run.run_id}>
                        <td className="mono">{run.run_id.slice(-8)}</td>
                        <td>{run.strategy_name ?? run.strategy?.name}</td>
                        <td className={Number(run.metrics?.total_return) >= 0 ? 'positive' : 'negative'}>{pct(run.metrics?.total_return)}</td>
                        <td>{pct(run.metrics?.excess_return)}</td>
                        <td>{num(run.metrics?.sharpe, 2)}</td>
                        <td>{pct(run.metrics?.max_drawdown)}</td>
                        <td>{usd(run.metrics?.transaction_costs)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="card">
            <div className="section-header">
              <div><div className="eyebrow">Execution ledger</div><h2>Trades and corporate events</h2></div>
              <span className="muted small">{result.trades?.length ?? 0} completed trades</span>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Date</th><th>Side</th><th>Quantity</th><th>Reference</th><th>Fill</th><th>Commission</th><th>Realized</th><th>Cash after</th></tr></thead>
                <tbody>
                  {(result.ledger ?? []).slice(-12).reverse().map((trade: Row, index: number) => (
                    <tr key={`${trade.date}-${index}`}>
                      <td className="mono">{trade.date}</td>
                      <td>{trade.side ?? trade.type}</td>
                      <td className="mono numeric">{trade.quantity ?? '—'}</td>
                      <td className="mono numeric">{trade.reference_price ? usd(trade.reference_price) : '—'}</td>
                      <td className="mono numeric">{trade.fill_price ? usd(trade.fill_price) : '—'}</td>
                      <td className="mono numeric">{trade.commission ? usd(trade.commission) : '—'}</td>
                      <td className={`mono numeric ${Number(trade.realized_pnl) >= 0 ? 'positive' : 'negative'}`}>{trade.realized_pnl ? usd(trade.realized_pnl) : '—'}</td>
                      <td className="mono numeric">{trade.cash_after ? usd(trade.cash_after) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <div className="split-2">
        <section className="card">
          <div className="section-header">
            <div><div className="eyebrow">Experiment history</div><h2>Saved research</h2></div>
            <span className="muted small">{experiments.length} experiment objects</span>
          </div>
          <div className="lab-history">
            {runs.length === 0 && <div className="muted small">No persisted runs yet.</div>}
            {runs.slice(0, 8).map((run) => (
              <button key={run.run_id} className="lab-history-row" onClick={() => void loadRun(run.run_id)}>
                <span>
                  <strong>{run.strategy_object_id?.slice(-8) ?? 'strategy'}</strong>
                  <span className="muted small">{String(run.start_date)} → {String(run.end_date)}</span>
                </span>
                <span className={Number(run.metrics?.total_return) >= 0 ? 'positive mono' : 'negative mono'}>{pct(run.metrics?.total_return)}</span>
                <span className="mono muted small">{run.run_id.slice(-8)}</span>
              </button>
            ))}
            {experiments.slice(0, 5).map((experiment) => (
              <button key={experiment.object_id} className="lab-history-row" onClick={() => void loadExperiment(experiment.object_id)}>
                <span>
                  <strong>{experiment.name}</strong>
                  <span className="muted small">experiment · {experiment.version}</span>
                </span>
                <span className="mono muted small">open</span>
              </button>
            ))}
          </div>
        </section>
        <section className="card">
          <div className="eyebrow">Method boundaries</div>
          <h2>What this result does not prove</h2>
          <ul className="lab-list">
            <li>This is an in-sample historical simulation; it is not an out-of-sample forecast.</li>
            <li>Next-open fills are conservative, but partial fills, queues, market impact and borrow are not modelled.</li>
            <li>Vendor price observations do not prove what a provider displayed on a historical date unless source bytes are archived.</li>
            <li>One instrument and one long-only path are supported in this vertical slice.</li>
            <li>A higher Sharpe ratio from one run is not statistical evidence of persistent alpha.</li>
          </ul>
        </section>
      </div>
    </div>
  )
}
