import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Badge, SectionHeader } from '../components/ui'

type Row = Record<string, any>
const pct = (value: unknown, digits = 2) =>
  value == null ? '—' : `${(Number(value) * 100).toFixed(digits)}%`
const num = (value: unknown, digits = 3) =>
  value == null ? '—' : Number(value).toFixed(digits)
const money = (value: unknown) =>
  value == null ? '—' : `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
const conclusionTone = (value: string) =>
  value === 'validation_supported_with_caveats' ? 'positive' : value === 'not_supported' ? 'negative' : 'warn'

function Metric({ label, value, detail, tone, testId }: {
  label: string; value: string; detail?: string; tone?: string; testId?: string
}) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${tone ?? ''}`} data-testid={testId}>{value}</div>
      {detail && <div className="muted small">{detail}</div>}
    </div>
  )
}

function CalibrationBars({ rows }: { rows: Row[] }) {
  const usable = rows.filter((row) => row.count)
  if (!usable.length) return <div className="muted small">No populated probability bins.</div>
  return (
    <div className="learning-calibration" role="img" aria-label="Calibration table">
      {usable.map((row) => (
        <div className="learning-cal-row" key={row.bin}>
          <span className="mono muted small">{pct(row.mean_probability, 0)}</span>
          <div className="learning-cal-track">
            <span className="learning-cal-predicted" style={{ width: `${Number(row.mean_probability) * 100}%` }} />
            <span className="learning-cal-observed" style={{ left: `${Number(row.observed_rate) * 100}%` }} />
          </div>
          <span className="mono small">{pct(row.observed_rate, 0)}</span>
          <span className="muted small">n={row.count}</span>
        </div>
      ))}
    </div>
  )
}

export default function Learning() {
  const [catalog, setCatalog] = useState<Row | null>(null)
  const [dataset, setDataset] = useState('')
  const [datasetInfo, setDatasetInfo] = useState<Row | null>(null)
  const [models, setModels] = useState<string[]>(['climatology', 'ridge', 'logistic', 'mlp'])
  const [features, setFeatures] = useState<string[]>(['mom_5', 'mom_20', 'vol_20', 'sma_gap_20', 'cs_mom_20_rank'])
  const [result, setResult] = useState<Row | null>(null)
  const [runs, setRuns] = useState<Row[]>([])
  const [applications, setApplications] = useState<Row[]>([])
  const [portfolio, setPortfolio] = useState<Row | null>(null)
  const [monitor, setMonitor] = useState<Row | null>(null)
  const [security, setSecurity] = useState('')
  const [threshold, setThreshold] = useState('50')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function loadRuns() {
    const [runPayload, appPayload] = await Promise.all([api.learningRuns(), api.learningApplications()])
    setRuns(runPayload.items)
    setApplications(appPayload.items)
  }

  useEffect(() => {
    Promise.all([api.learningCatalog(), api.learningRuns(), api.learningApplications()])
      .then(([cat, runPayload, appPayload]) => {
        setCatalog(cat)
        setRuns(runPayload.items)
        setApplications(appPayload.items)
        const first = cat.datasets?.[0]?.dataset_id ?? ''
        setDataset(first)
      })
      .catch((caught: Error) => setError(caught.message))
  }, [])

  useEffect(() => {
    if (!dataset) return
    api.learningDataset(dataset)
      .then((payload) => {
        setDatasetInfo(payload)
        setSecurity(payload.instruments?.[0]?.security_id ?? '')
      })
      .catch((caught: Error) => setError(caught.message))
  }, [dataset])

  const instruments = useMemo(() => (datasetInfo?.instruments ?? []) as Row[], [datasetInfo])

  function toggle(list: string[], value: string, set: (next: string[]) => void) {
    set(list.includes(value) ? list.filter((item) => item !== value) : [...list, value])
  }

  async function runExperiment() {
    setBusy('experiment'); setError(null); setMessage(null); setPortfolio(null); setMonitor(null)
    try {
      const payload = await api.learningExperiment({
        dataset, models, features, target: 'direction', persist: true,
      })
      setResult(payload)
      setMessage(`Experiment ${payload.run_id} · ${payload.conclusion}`)
      await loadRuns()
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function buildPortfolio() {
    if (!result || !security) return
    setBusy('portfolio'); setError(null); setMessage(null)
    try {
      const payload = await api.learningPortfolio(result.run_id, {
        security_id: security, threshold: Number(threshold) / 100,
      })
      setPortfolio(payload)
      setMessage('Frozen test forecasts passed through the event-driven portfolio ledger.')
      await loadRuns()
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function checkMonitor() {
    if (!result) return
    setBusy('monitor'); setError(null)
    try {
      setMonitor(await api.learningMonitor(result.run_id))
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function saveApplication() {
    if (!result) return
    setBusy('save'); setError(null)
    try {
      const payload = await api.learningApplication({
        run_id: result.run_id,
        name: `Learning research · ${new Date().toISOString()}`,
        purpose: 'Persisted chronological forecast experiment with audit and research memory.',
      })
      setMessage(`Saved research application ${payload.object_id}`)
      await loadRuns()
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function openRun(runId: string) {
    setBusy('open'); setError(null)
    try {
      const payload = await api.learningRun(runId)
      setResult(payload)
      setPortfolio(null); setMonitor(null)
      setMessage(`Reopened ${runId}`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  return (
    <div className="page learning-page">
      <div className="section-header">
        <div>
          <div className="eyebrow">Quant Lab · Learning Brain</div>
          <h1>Learning Lab</h1>
          <p className="section-detail">
            A chronological forecasting experiment: point-in-time features, competing baselines,
            calibrated probabilities, an untouched test interval, and a separate forecast-to-portfolio decision.
          </p>
        </div>
        <div className="section-actions">
          <Link className="button" to="/lab">Strategy lab</Link>
          <Link className="button" to="/lab/institutional">Risk &amp; pricing</Link>
          <Badge tone="accent">Observed demo panel</Badge>
          <Badge tone="warn">Not point-in-time verified</Badge>
        </div>
      </div>

      {error && <div className="banner banner-warn error-text" data-testid="learn-error">{error}</div>}
      {message && <div className="banner banner-info" data-testid="learn-message">{message}</div>}

      <div className="split-2">
        <section className="card">
          <SectionHeader eyebrow="Data fabric v2" title="Dataset"
            detail="Provider observations and rights are shown before a model is trained." />
          <div className="lab-field">
            <label htmlFor="learning-dataset">Dataset</label>
            <select id="learning-dataset" className="field" value={dataset} onChange={(event) => setDataset(event.target.value)}>
              {(catalog?.datasets ?? []).map((item: Row) => (
                <option key={item.dataset_id} value={item.dataset_id}>{item.name} · {item.securities} securities</option>
              ))}
            </select>
          </div>
          {datasetInfo && (
            <>
              <p className="small" style={{ margin: "8px 0 0" }}>
                <strong data-testid="learn-dataset-name">{datasetInfo.name}</strong>
                <span className="muted"> · {datasetInfo.rights} rights · {datasetInfo.data_class}</span>
              </p>
              <div className="kv" style={{ marginTop: 12 }}>
                <dt>Data class</dt><dd>{datasetInfo.data_class}</dd>
                <dt>Rights</dt><dd>{datasetInfo.rights}</dd>
                <dt>Coverage</dt><dd>{datasetInfo.coverage?.securities} securities · {datasetInfo.coverage?.sessions} sessions</dd>
                <dt>Period</dt><dd className="mono">{datasetInfo.coverage?.start} → {datasetInfo.coverage?.end}</dd>
                <dt>Adjustment</dt><dd>{datasetInfo.coverage?.adjustment}</dd>
                <dt>Historical vintage</dt><dd>{datasetInfo.coverage?.historical_vintage}</dd>
              </div>
              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table className="mini-table">
                  <thead><tr><th>Ticker</th><th>Name</th><th>Sessions</th></tr></thead>
                  <tbody>{instruments.map((item) => (
                    <tr key={item.security_id}><td className="mono">{item.ticker}</td><td>{item.name}</td><td className="mono numeric">{item.sessions}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              <p className="notice small">Quality: {datasetInfo.quality_summary?.errors} error(s), {datasetInfo.quality_summary?.warnings} warning(s). {datasetInfo.quality?.[0]?.detail ?? ''}</p>
              <p className="notice small mono break">Panel SHA-256 {datasetInfo.content_hash}</p>
            </>
          )}
        </section>

        <section className="card">
          <SectionHeader eyebrow="Experiment specification" title="What will be tested"
            detail="The test interval is selected after validation and is not used for tuning." />
          <div className="learning-checks">
            <div>
              <h4>Models</h4>
              {(catalog?.models ?? []).map((item: Row) => (
                <label className="learning-check" key={item.key}>
                  <input type="checkbox" checked={models.includes(item.key)}
                    onChange={() => toggle(models, item.key, setModels)} />
                  <span><strong>{item.label}</strong><span className="muted small">{item.description}</span></span>
                </label>
              ))}
            </div>
            <div>
              <h4>Point-in-time features</h4>
              {(catalog?.features?.features ?? []).map((item: Row) => (
                <label className="learning-check" key={item.key}>
                  <input type="checkbox" checked={features.includes(item.key)}
                    onChange={() => toggle(features, item.key, setFeatures)} />
                  <span><strong>{item.label}</strong><span className="muted small">{item.formula}</span></span>
                </label>
              ))}
            </div>
          </div>
          <div className="lab-credibility" style={{ marginTop: 12 }}>
            <div><span>Target</span><strong>Next-session direction</strong></div>
            <div><span>Horizon</span><strong>1 session</strong></div>
            <div><span>Selection</span><strong>Validation Brier</strong></div>
            <div><span>Calibration</span><strong>Platt on validation</strong></div>
          </div>
          <button className="button button-primary" onClick={runExperiment} disabled={busy !== null || !models.length || !features.length}>
            {busy === 'experiment' ? 'Training and evaluating…' : 'Run experiment'}
          </button>
        </section>
      </div>

      {result && (
        <>
          <section className="card" data-testid="learning-result">
            <SectionHeader eyebrow="Scientific result" title="The claim, the test, and the caveat"
              detail={`${result.run_id} · data ${result.dataset?.data_class} · ${result.selection?.candidates} candidates retained`}
              actions={<Badge tone={conclusionTone(result.conclusion) as any}>{result.conclusion?.replaceAll('_', ' ')}</Badge>} />
            <div className="metric-grid" style={{ marginTop: 12 }}>
              <Metric label="Selected model" value={result.selection?.selected_model ?? '—'} detail={`validation Brier ${num(result.selection?.brier, 4)}`} />
              <Metric label="Test Brier" value={num(result.test?.brier, 4)} detail={`climatology ${num(result.baseline?.brier, 4)}`} testId="learn-brier" />
              <Metric label="Brier skill" value={pct(result.test?.brier_skill_vs_climatology, 3)} tone={Number(result.test?.brier_skill_vs_climatology) > 0 ? 'positive' : 'negative'} />
              <Metric label="Log loss" value={num(result.test?.log_loss, 4)} detail={`AUC ${num(result.test?.auc, 3)}`} />
              <Metric label="Accuracy" value={pct(result.test?.accuracy_at_half, 2)} detail={`prevalence ${pct(result.test?.prevalence, 2)}`} />
              <Metric label="Test rows" value={String(result.test?.observations ?? '—')} detail={`${result.split?.test?.sessions} sessions`} />
            </div>
            <div className="banner banner-warn" style={{ marginTop: 12 }}>
              <strong>{result.conclusion?.replaceAll('_', ' ')}.</strong>{' '}
              {result.conclusion === 'validation_supported_with_caveats'
                ? 'The interval excludes zero, but this is forecast accuracy evidence, not proof of trading profit.'
                : 'The model did not establish an out-of-sample accuracy advantage over climatology. The negative result is retained.'}
            </div>
            <div className="split-2" style={{ marginTop: 14 }}>
              <div>
                <h4>Chronological split</h4>
                <table className="mini-table">
                  <thead><tr><th>Partition</th><th>Start</th><th>End</th><th>Rows</th></tr></thead>
                  <tbody>{['train', 'validation', 'test'].map((key) => (
                    <tr key={key}><td>{key}</td><td className="mono small">{result.split?.[key]?.start}</td>
                      <td className="mono small">{result.split?.[key]?.end}</td><td className="mono numeric">{result.split?.[key]?.rows}</td></tr>
                  ))}</tbody>
                </table>
                <p className="notice small">Embargo {result.split?.embargo} sessions · test used for selection: {String(result.split?.test_used_for_selection)}</p>
              </div>
              <div>
                <h4>Continuous companion</h4>
                <div className="kv">
                  <dt>Next-session return RMSE</dt><dd>{num(result.continuous?.metrics?.rmse, 5)}</dd>
                  <dt>MAE</dt><dd>{num(result.continuous?.metrics?.mae, 5)}</dd>
                  <dt>90% interval coverage</dt><dd>{pct(result.continuous?.metrics?.interval_coverage, 1)}</dd>
                  <dt>Interval method</dt><dd className="small">{result.continuous?.metrics?.interval}</dd>
                </div>
              </div>
            </div>
          </section>

          <div className="split-2">
            <section className="card">
              <SectionHeader eyebrow="Probability calibration" title="Reliability on the untouched test"
                detail="Predicted bin mean versus observed outcome rate. Platt scaling was fitted on validation only." />
              <CalibrationBars rows={result.test?.calibration ?? []} />
              <p className="notice small">Expected calibration error {pct(result.test?.calibration_error, 2)} · Brier {num(result.test?.brier, 4)}</p>
              <div className="table-wrap" style={{ marginTop: 10 }}>
                <table className="mini-table">
                  <thead><tr><th>Model</th><th>Validation Brier</th><th>Status</th></tr></thead>
                  <tbody>{(result.attempts ?? []).map((item: Row) => (
                    <tr key={item.model}><td>{item.label ?? item.model}</td>
                      <td className="mono numeric">{num(item.metrics?.brier, 4)}</td>
                      <td>{item.status === 'succeeded' ? (item.selected ? 'selected' : `rank ${item.rank}`) : 'failed'}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </section>

            <section className="card">
              <SectionHeader eyebrow="Model auditor" title="Specific findings, not a score"
                detail={`${result.audit?.counts?.error ?? 0} error(s) · ${result.audit?.counts?.warning ?? 0} warning(s)`} />
              <div className="learning-findings">
                {(result.audit?.findings ?? []).map((item: Row) => (
                  <div className={`learning-finding is-${item.severity}`} key={item.finding_key}>
                    <div><strong>{item.finding_key?.replaceAll('_', ' ')}</strong><span className="badge badge-neutral">{item.severity}</span></div>
                    <p>{item.summary}</p>
                    <span className="muted small">{item.limitation}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <section className="card">
            <SectionHeader eyebrow="Decision layer" title="Forecast to portfolio"
              detail="A frozen test forecast is mapped to a declared long-only threshold rule and executed by the existing event-driven simulator." />
            <div className="learning-decision">
              <div className="lab-field">
                <label htmlFor="learning-security">Instrument</label>
                <select id="learning-security" className="field" value={security} onChange={(event) => setSecurity(event.target.value)}>
                  {instruments.map((item) => <option key={item.security_id} value={item.security_id}>{item.ticker} · {item.name}</option>)}
                </select>
              </div>
              <div className="lab-field">
                <label htmlFor="learning-threshold">Long threshold (%)</label>
                <input id="learning-threshold" className="field mono" type="number" step="1" value={threshold}
                  onChange={(event) => setThreshold(event.target.value)} />
              </div>
              <button className="button" onClick={buildPortfolio} disabled={busy !== null}>
                {busy === 'portfolio' ? 'Simulating…' : 'Run portfolio rule'}
              </button>
              <button className="button" onClick={checkMonitor} disabled={busy !== null}>Check monitor</button>
              <button className="button" onClick={saveApplication} disabled={busy !== null}>Save application</button>
            </div>
            {portfolio && (
              <div data-testid="learning-portfolio" style={{ marginTop: 14 }}>
                <div className="metric-grid">
                  <Metric label="Strategy return" value={pct(portfolio.backtest?.metrics?.total_return)} tone={Number(portfolio.backtest?.metrics?.total_return) >= 0 ? 'positive' : 'negative'} />
                  <Metric label="Buy & hold" value={pct(portfolio.backtest?.metrics?.benchmark?.total_return)} />
                  <Metric label="Excess" value={pct(portfolio.backtest?.metrics?.excess_return)} />
                  <Metric label="Sharpe" value={num(portfolio.backtest?.metrics?.sharpe, 3)} />
                  <Metric label="Max drawdown" value={pct(portfolio.backtest?.metrics?.max_drawdown)} tone="negative" />
                  <Metric label="Sessions" value={String(portfolio.backtest?.metrics?.sessions ?? '—')} detail={`$${money(portfolio.backtest?.metrics?.transaction_costs)} costs`} />
                </div>
                <p className="notice small">
                  Accounting reconciled: {String(portfolio.backtest?.reconciliation?.reconciled)} · strategy object {portfolio.backtest?.strategy_object_id} ·
                  {' '}A positive forecast result is not automatically a profitable rule.
                </p>
              </div>
            )}
          </section>

          {monitor && (
            <section className="card" data-testid="learning-monitor">
              <SectionHeader eyebrow="Sentinel" title="Monitoring observations" detail="No automatic retraining or deployment." />
              <div className="table-wrap">
                <table className="mini-table">
                  <thead><tr><th>Feature</th><th>Recent mean</th><th>Training mean</th><th>Standardised shift</th><th>Rows</th></tr></thead>
                  <tbody>{(monitor.drift?.features ?? []).map((item: Row) => (
                    <tr key={item.feature}><td>{item.feature}</td><td className="mono numeric">{num(item.recent_mean, 5)}</td>
                      <td className="mono numeric">{num(item.training_mean, 5)}</td><td className="mono numeric">{num(item.standardised_shift, 2)}</td>
                      <td className="mono numeric">{item.sessions}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              <p className="notice small">{monitor.drift?.note}</p>
            </section>
          )}
        </>
      )}

      <div className="split-2">
        <section className="card">
          <SectionHeader eyebrow="Research memory" title="Experiments and failed hypotheses"
            detail={`${runs.length} stored run(s) · the ledger works without an LLM.`} />
          <div className="lab-history">
            {runs.map((run) => (
              <button key={run.run_id} className="lab-history-row" onClick={() => void openRun(run.run_id)}>
                <span><strong>{run.run_id}</strong><span className="muted small">{run.dataset_id} · {run.selected_model} · {run.conclusion?.replaceAll('_', ' ')}</span></span>
                <span className="mono muted small">{num(run.test_brier, 4)}</span>
              </button>
            ))}
            {runs.length === 0 && <div className="muted small">No experiments yet. Run one above.</div>}
          </div>
        </section>
        <section className="card">
          <SectionHeader eyebrow="Saved applications" title="Forecast research artifacts"
            detail={`${applications.length} application object(s).`} />
          <div className="lab-history">
            {applications.slice(0, 8).map((application) => (
              <div className="lab-history-row" key={application.object_id}>
                <span><strong>{application.name}</strong><span className="muted small">{application.object_id}</span></span>
                <span className="mono muted small">{application.status}</span>
              </div>
            ))}
            {applications.length === 0 && <div className="muted small">Save a run or portfolio decision to create one.</div>}
          </div>
          <ul className="lab-list">
            <li>This page reports observed market observations, not point-in-time verified vintages.</li>
            <li>Restricted vendor data stays in the local database; it is not committed.</li>
            <li>A lower Brier score is a forecast-accuracy result, not an alpha claim.</li>
            <li>Failed and inconclusive experiments remain in the memory list.</li>
          </ul>
        </section>
      </div>
    </div>
  )
}
