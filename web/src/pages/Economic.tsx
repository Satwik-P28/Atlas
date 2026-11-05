import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Badge, SectionHeader } from '../components/ui'

type Row = Record<string, any>

const pct = (value: unknown, digits = 2) =>
  value == null ? '—' : `${(Number(value) * 100).toFixed(digits)}%`
const bps = (value: unknown) =>
  value == null ? '—' : `${(Number(value) * 10_000).toFixed(1)} bp`
const num = (value: unknown, digits = 2) =>
  value == null ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits })
const money = (value: unknown) =>
  value == null
    ? '—'
    : `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
const compact = (value: unknown) =>
  value == null ? '—' : new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value))
const short = (value: unknown, length = 8) => String(value ?? '').slice(-length)
const tone = (value: string) =>
  value.includes('unstable') || value === 'not_supported' ? 'warn'
    : value === 'association_supported_with_caveats' ? 'positive'
      : value === 'not_identified' ? 'warn' : 'neutral'

function Metric({ label, value, detail, tone: color, testId }: {
  label: string; value: string; detail?: string; tone?: string; testId?: string
}) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${color ?? ''}`} data-testid={testId}>{value}</div>
      {detail && <div className="muted small">{detail}</div>}
    </div>
  )
}

function WeatherDemandChart({ rows }: { rows: Row[] }) {
  if (!rows.length) return <div className="muted small">No complete daily observations.</div>
  const width = 940
  const height = 236
  const padX = 10
  const padY = 20
  const demand = rows.map((row) => Number(row.demand_mean_mw))
  const temperature = rows.map((row) => Number(row.temperature_mean_c))
  const dMin = Math.min(...demand) - 1500
  const dMax = Math.max(...demand) + 1500
  const tMin = Math.min(...temperature) - 2
  const tMax = Math.max(...temperature) + 2
  const x = (index: number) => padX + (index / Math.max(rows.length - 1, 1)) * (width - padX * 2)
  const yD = (value: number) => height - padY - ((value - dMin) / (dMax - dMin)) * (height - padY * 2)
  const yT = (value: number) => height - padY - ((value - tMin) / (tMax - tMin)) * (height - padY * 2)
  const line = (values: number[], scale: (value: number) => number) =>
    values.map((value, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)},${scale(value).toFixed(1)}`).join(' ')
  const ticks = [0.2, 0.4, 0.6, 0.8]
  const labels = [0, Math.floor(rows.length / 4), Math.floor(rows.length / 2), Math.floor((3 * rows.length) / 4), rows.length - 1]
  return (
    <div className="econ-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img"
        aria-label="Daily ERCOT mean demand and Dallas mean temperature for 2023">
        {ticks.map((tick) => (
          <line key={tick} x1={padX} x2={width - padX} y1={height - padY - tick * (height - padY * 2)}
            y2={height - padY - tick * (height - padY * 2)} className="econ-grid" />
        ))}
        <path d={line(demand, yD)} className="econ-line-demand" />
        <path d={line(temperature, yT)} className="econ-line-temperature" />
        {labels.map((index) => (
          <text key={index} x={x(index)} y={height - 3} textAnchor="middle" className="econ-axis-label">
            {rows[index]?.date?.slice(5)}
          </text>
        ))}
      </svg>
      <div className="econ-legend">
        <span><i className="econ-swatch-demand" /> ERCOT mean demand · {compact(dMin + 1500)}–{compact(dMax - 1500)} MW</span>
        <span><i className="econ-swatch-temperature" /> Dallas mean temp · {num(tMin + 2, 1)}–{num(tMax - 2, 1)} °C</span>
        <span className="muted">Independent axes; a shared line does not imply shared units.</span>
      </div>
    </div>
  )
}

export default function Economic() {
  const [catalog, setCatalog] = useState<Row | null>(null)
  const [panel, setPanel] = useState<Row | null>(null)
  const [graph, setGraph] = useState<Row | null>(null)
  const [conflicts, setConflicts] = useState<Row | null>(null)
  const [run, setRun] = useState<Row | null>(null)
  const [scenario, setScenario] = useState<Row | null>(null)
  const [runs, setRuns] = useState<Row[]>([])
  const [memory, setMemory] = useState<Row | null>(null)
  const [sentinel, setSentinel] = useState<Row | null>(null)
  const [replay, setReplay] = useState<Row | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [shock, setShock] = useState('2')
  const [price, setPrice] = useState('65')
  const [consumption, setConsumption] = useState('50000')
  const [exposure, setExposure] = useState('50')
  const [unhedged, setUnhedged] = useState('60')
  const [revenue, setRevenue] = useState('40000000')
  const [tax, setTax] = useState('21')
  const [cutoff, setCutoff] = useState('2023-12-31')

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [cat, panelData, graphData, conflictData, runData, memoryData, sentinelData] = await Promise.all([
          api.economicCatalog(), api.economicPanel(), api.economicGraph(),
          api.economicConflicts(), api.economicRuns(), api.economicMemory(), api.economicSentinel(),
        ])
        if (cancelled) return
        setCatalog(cat)
        setPanel(panelData)
        setGraph(graphData)
        setConflicts(conflictData)
        setRuns(runData.items ?? [])
        setMemory(memoryData)
        setSentinel(sentinelData)
        const first = runData.items?.[0]
        if (first) {
          const full = await api.economicRun(first.run_id)
          if (cancelled) return
          setRun(full)
          const saved = await api.economicScenarios(first.run_id)
          if (!cancelled) {
            const latest = saved.items?.[0]?.result ?? null
            setScenario(latest)
            loadScenarioInputs(latest)
          }
        }
      } catch (caught) {
        if (!cancelled) setError((caught as Error).message)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const publicSources = useMemo(
    () => (catalog?.sources ?? []).filter((source: Row) => source.source_id !== 'atlas-assumption'),
    [catalog],
  )
  const daily = useMemo(() => (panel?.rows ?? []) as Row[], [panel])
  const firstConflict = conflicts?.items?.[0] ?? null
  const staleRuns = (sentinel?.stale_runs ?? []) as Row[]

  function loadScenarioInputs(value: Row | null) {
    if (!value) return
    const f = value.financial ?? {}
    setShock(String(value.shock_c ?? 2))
    setConsumption(String(f.annual_consumption_mwh ?? 50_000))
    setExposure(String(Number(f.load_sensitivity ?? 0.5) * 100))
    setUnhedged(String(Number(f.unhedged_fraction ?? 0.6) * 100))
    setPrice(String(f.power_price_usd_mwh ?? 65))
    setRevenue(String(f.revenue_usd ?? 40_000_000))
    setTax(String(Number(f.tax_rate ?? 0.21) * 100))
  }

  async function refreshRuns() {
    const [runData, memoryData, sentinelData] = await Promise.all([
      api.economicRuns(), api.economicMemory(), api.economicSentinel(),
    ])
    setRuns(runData.items ?? [])
    setMemory(memoryData)
    setSentinel(sentinelData)
  }

  async function openRun(runId: string) {
    setBusy('open'); setError(null); setReplay(null)
    try {
      const full = await api.economicRun(runId)
      setRun(full)
      const saved = await api.economicScenarios(runId)
      const latest = saved.items?.[0]?.result ?? null
      setScenario(latest)
      loadScenarioInputs(latest)
      setMessage(`Reopened ${runId}; observations remain frozen in the saved run.`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function runStudy() {
    setBusy('analyze'); setError(null); setMessage(null); setReplay(null)
    try {
      const payload = await api.economicAnalyze({
        as_of: new Date().toISOString(), mode: 'public_available', persist: true, seed: 20261105,
      })
      setRun(payload)
      const scenarioPayload = await api.economicScenario(payload.run_id, {
        shock_c: Number(shock), annual_consumption_mwh: Number(consumption),
        load_sensitivity: Number(exposure) / 100, unhedged_fraction: Number(unhedged) / 100,
        power_price_usd_mwh: Number(price), revenue_usd: Number(revenue),
        tax_rate: Number(tax) / 100, draws: 2000, seed: 20261105,
      })
      setScenario(scenarioPayload)
      loadScenarioInputs(scenarioPayload)
      await refreshRuns()
      setMessage(`New chronological experiment ${payload.run_id}; the test interval was not used for selection.`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function executeScenario() {
    if (!run) return
    setBusy('scenario'); setError(null); setMessage(null)
    try {
      const payload = await api.economicScenario(run.run_id, {
        shock_c: Number(shock), annual_consumption_mwh: Number(consumption),
        load_sensitivity: Number(exposure) / 100, unhedged_fraction: Number(unhedged) / 100,
        power_price_usd_mwh: Number(price), revenue_usd: Number(revenue),
        tax_rate: Number(tax) / 100, draws: 2000, seed: 20261105,
      })
      setScenario(payload)
      loadScenarioInputs(payload)
      setMessage('Scenario executed through the Financial-Economic Compiler; hypothetical exposure assumptions are unchanged.')
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function saveStudy() {
    if (!run) return
    setBusy('save'); setError(null); setMessage(null)
    try {
      const payload = await api.economicSaveApplication({
        run_id: run.run_id, scenario_id: scenario?.scenario_id ?? null,
        name: `Weather → electricity → margin · ${short(run.run_id)}`,
        purpose: 'Public NOAA/EIA association, hypothetical manufacturing exposure and a reproducible financial scenario.',
      })
      setMessage(`Saved research application ${payload.object_id}. Reopen it to inspect the frozen evidence and scenario.`)
      await refreshRuns()
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function refreshSentinel() {
    setBusy('sentinel'); setError(null)
    try {
      setSentinel(await api.economicSentinel())
      setMessage('Source freshness, dependencies and alerts refreshed. No model was retrained or deployed.')
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function checkReplay() {
    if (!run) return
    setBusy('replay'); setError(null)
    try {
      setReplay(await api.economicReplay(run.run_id, `${cutoff}T23:59:59Z`))
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function applyCorrection() {
    if (!firstConflict?.claims?.[0]?.observation_id) return
    setBusy('revision'); setError(null)
    try {
      const result = await api.economicRevision(firstConflict.claims[0].observation_id, {
        value: 35.7, reason: 'UI correction drill: review station discrepancy, no source winner selected',
      })
      await refreshRuns()
      if (run) setRun(await api.economicRun(run.run_id))
      setMessage(`Revision ${result.revision_seq} recorded. ${result.stale_runs.length} dependent run(s) marked stale; the old observation remains.`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  return (
    <div className="page economic-page">
      <div className="section-header">
        <div>
          <div className="eyebrow">Quant Lab · Economic intelligence</div>
          <h1>Weather, electricity, financial consequence</h1>
          <p className="section-detail">
            A public-data research chain from Dallas weather and ERCOT demand to a conditional
            association, then to an explicitly hypothetical manufacturer. Every transition keeps
            its evidence class.
          </p>
        </div>
        <div className="section-actions">
          <Link className="button" to="/lab">Strategy lab</Link>
          <Link className="button" to="/lab/learning">Learning lab</Link>
          <Badge tone="accent">Observed public archive</Badge>
          <Badge tone="warn">No historical vintage</Badge>
        </div>
      </div>

      {error && <div className="banner banner-warn error-text" data-testid="econ-error">{error}</div>}
      {message && <div className="banner banner-info" data-testid="econ-message">{message}</div>}

      <div className="split-2">
        <section className="card">
          <SectionHeader eyebrow="Stage A + B · Evidence fabric" title="Two public source families"
            detail="A weather observation is not a forecast. The current archive is a retrieval proxy, not an as-issued historical vintage."
            actions={<Badge tone="accent">365 aligned days</Badge>} />
          <div className="econ-source-grid">
            {publicSources.map((source: Row) => (
              <a className="source-card econ-source" href={source.homepage} target="_blank" rel="noreferrer" key={source.source_id}>
                <div className="eyebrow">{source.kind?.replaceAll('_', ' ')}</div>
                <div className="source-name">{source.name}</div>
                <div className="muted small">{source.licence} · redistribution {source.redistribution}</div>
                <div className="mono small">{source.source_id}</div>
              </a>
            ))}
          </div>
          <div className="kv" style={{ marginTop: 12 }}>
            <dt>Panel</dt><dd className="mono">{panel?.start} → {panel?.end} · {panel?.row_count} daily rows</dd>
            <dt>Geography</dt><dd>ERCOT balancing authority · Dallas–Fort Worth stations</dd>
            <dt>Demand</dt><dd>{num(catalog?.summary?.demand_mean_mw?.mean, 0)} MW mean · {num(catalog?.summary?.demand_mean_mw?.max, 0)} MW daily max</dd>
            <dt>Station spread</dt><dd>{num(catalog?.summary?.station_max_temperature_difference_c?.max, 1)} °C maximum TMAX disagreement</dd>
            <dt>SHA-256</dt><dd className="mono break">{catalog?.fixture?.panel?.sha256}</dd>
          </div>
          <p className="notice small">
            EIA-930 is operator-submitted balancing data. GHCN-Daily is quality-controlled station data.
            Neither archive proves what a researcher could have seen on the operating date.
          </p>
        </section>

        <section className="card">
          <SectionHeader eyebrow="Stage C · Chronological experiment" title="Fit once. Select on validation."
            detail="The seasonal baseline and two degree-day forms share a 70/15/15 chronological split. The last 55 days are untouched until the final evaluation."
            actions={<Badge tone="warn">Association, not causation</Badge>} />
          <div className="econ-pipeline">
            {['Observed weather', 'Regional demand', 'Conditional association', 'Hypothetical exposure', 'Financial consequence'].map((label, index) => (
              <div className={`econ-pipeline-step ${index < 3 ? 'is-observed' : 'is-hypothetical'}`} key={label}>
                <span>{String(index + 1).padStart(2, '0')}</span>{label}
              </div>
            ))}
          </div>
          <div className="econ-actions">
            <button className="button button-primary" onClick={runStudy} disabled={busy !== null} data-testid="econ-run">
              {busy === 'analyze' ? 'Fitting and evaluating…' : 'Run chronological study'}
            </button>
            <button className="button" onClick={saveStudy} disabled={!run || busy !== null} data-testid="econ-save">
              Save research application
            </button>
          </div>
          <p className="notice small">
            {catalog?.causal_policy?.rule ?? 'A regression with controls is not a causal estimate.'}
          </p>
        </section>
      </div>

      <section className="card">
        <SectionHeader eyebrow="Synchronized series" title="2023 daily weather and regional load"
          detail="Station mean temperature and ERCOT mean demand share a date key, not a unit or a causal mechanism."
          actions={<Badge tone="neutral">Independent y-axes</Badge>} />
        <WeatherDemandChart rows={daily} />
      </section>

      {run && (
        <>
          <section className="card" data-testid="econ-result">
            <SectionHeader eyebrow="Stage D · Scientific result" title="What the untouched test supports"
              detail={`${run.run_id} · seed ${run.seed} · ${run.duration_ms} ms`}
              actions={<Badge tone={tone(run.conclusion)}>{run.conclusion?.replaceAll('_', ' ')}</Badge>} />
            <div className="metric-grid">
              <Metric label="Selected form" value={run.selection?.selected_model?.replaceAll('_', ' ') ?? '—'}
                detail={`chosen by ${run.selection?.criterion}`} />
              <Metric label="Validation RMSE" value={`${num(run.selection?.validation_rmse, 0)} MW`}
                detail="model selection only" />
              <Metric label="Test RMSE" value={`${num(run.test?.rmse, 0)} MW`}
                detail={`seasonal ${num(run.baseline?.rmse, 0)} MW`} testId="econ-rmse" />
              <Metric label="RMSE skill" value={pct(run.skill_vs_seasonal, 1)}
                tone={Number(run.skill_vs_seasonal) > 0 ? 'positive' : 'negative'}
                detail="versus seasonal baseline" />
              <Metric label="Test R²" value={num(run.test?.r2, 3)} tone="negative"
                detail={`mean error ${num(run.test?.mean_error, 0)} MW`} testId="econ-r2" />
              <Metric label="Test rows" value={String(run.test?.observations ?? '—')}
                detail={`${run.split?.test?.start} → ${run.split?.test?.end}`} />
            </div>
            <div className="banner banner-warn" style={{ marginTop: 12 }} data-testid="econ-warning">
              <strong>Forecast instability disclosed.</strong> The selected model beats the seasonal
              RMSE baseline but has a negative test R² and a large positive late-year bias. This is
              evidence of a conditional association in one place and year, not a stable load forecast.
            </div>
            <div className="split-2" style={{ marginTop: 14 }}>
              <div>
                <h4>Split audit</h4>
                <table className="mini-table">
                  <thead><tr><th>Partition</th><th>Start</th><th>End</th><th>Rows</th></tr></thead>
                  <tbody>{['train', 'validation', 'test'].map((key) => (
                    <tr key={key}><td>{key}</td><td className="mono small">{run.split?.[key]?.start}</td>
                      <td className="mono small">{run.split?.[key]?.end}</td>
                      <td className="mono numeric">{run.split?.[key]?.rows}</td></tr>
                  ))}</tbody>
                </table>
                <p className="notice small">Test used for selection: <strong>{String(run.split?.test_used_for_selection)}</strong>. Embargo: {run.split?.embargo} rows.</p>
              </div>
              <div>
                <h4>Alternative forms on the same test</h4>
                <table className="mini-table">
                  <thead><tr><th>Form</th><th>Test RMSE</th><th>Test R²</th></tr></thead>
                  <tbody>{Object.entries(run.candidates ?? {}).map(([name, metric]: [string, any]) => (
                    <tr key={name}><td>{name.replaceAll('_', ' ')}</td>
                      <td className="mono numeric">{num(metric?.rmse, 0)}</td>
                      <td className="mono numeric">{num(metric?.r2, 3)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
          </section>

          <div className="split-2">
            <section className="card">
              <SectionHeader eyebrow="Stage D · Causal boundary" title="The coefficient is an association"
                detail="Same-day weather is not randomly assigned. No treatment timing or comparison group identifies a causal effect."
                actions={<Badge tone="warn">not identified</Badge>} />
              <div className="econ-causal">
                <div><span>Reported quantity</span><strong>{num(run.association_effect?.estimate_mw_per_c, 0)} MW / °C</strong></div>
                <div><span>95% sampling interval</span><strong>{num(run.association_effect?.interval_95?.[0], 0)} – {num(run.association_effect?.interval_95?.[1], 0)} MW</strong></div>
                <div><span>Interpretation</span><strong>conditional association</strong></div>
                <div><span>Identification</span><strong>none declared</strong></div>
              </div>
              <p className="notice small">
                The interval describes sampling uncertainty for this conditional association. It is
                not a causal confidence interval. The DiD and interrupted-time-series estimators can
                carry a causal label only when their design assumptions are defended.
              </p>
              <details className="econ-details">
                <summary>Inspect model assumptions and findings</summary>
                <ul className="plain small">
                  {(run.model?.assumptions ?? []).map((item: string) => <li key={item}>· {item}</li>)}
                </ul>
                <div className="econ-findings">
                  {(run.audit?.findings ?? []).map((item: Row) => (
                    <div className={`learning-finding is-${item.severity}`} key={item.finding_key}>
                      <div><strong>{item.finding_key?.replaceAll('_', ' ')}</strong><span className="badge badge-neutral">{item.severity}</span></div>
                      <p>{item.summary}</p>
                    </div>
                  ))}
                </div>
              </details>
            </section>

            <section className="card">
              <SectionHeader eyebrow="Stage E + F · Scenario" title="Hypothetical operating exposure"
                detail="These are user assumptions, not observed company contracts or facility loads."
                actions={<Badge tone="warn">Hypothetical firm</Badge>} />
              <div className="econ-controls">
                <label>Temperature shock (°C)<input className="field mono" type="number" step="0.5" min="-10" max="10" value={shock} onChange={(e) => setShock(e.target.value)} /></label>
                <label>Power price ($/MWh)<input className="field mono" type="number" min="0" step="1" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
                <label>Annual consumption (MWh)<input className="field mono" type="number" min="0" step="1000" value={consumption} onChange={(e) => setConsumption(e.target.value)} /></label>
                <label>Demand pass-through (%)<input className="field mono" type="number" min="0" step="5" value={exposure} onChange={(e) => setExposure(e.target.value)} /></label>
                <label>Unhedged (%)<input className="field mono" type="number" min="0" max="100" step="5" value={unhedged} onChange={(e) => setUnhedged(e.target.value)} /></label>
                <label>Revenue ($)<input className="field mono" type="number" min="1" step="1000000" value={revenue} onChange={(e) => setRevenue(e.target.value)} /></label>
                <label>Tax rate (%)<input className="field mono" type="number" min="0" max="100" step="1" value={tax} onChange={(e) => setTax(e.target.value)} /></label>
              </div>
              <div className="econ-actions">
                <button className="button button-primary" onClick={executeScenario} disabled={busy !== null} data-testid="econ-scenario">
                  {busy === 'scenario' ? 'Compiling scenario…' : 'Recompute dependent scenario'}
                </button>
                <span className="muted small">Monte Carlo draws: 2,000 · seed 20261105</span>
              </div>
              {scenario && (
                <div data-testid="econ-scenario-result">
                  <div className="metric-grid" style={{ marginTop: 12 }}>
                    <Metric label="Demand response" value={pct(scenario.demand?.change_fraction, 2)}
                      detail={`reference ${num(scenario.reference_temperature_c, 1)} °C`} testId="econ-demand" />
                    <Metric label="Unhedged energy delta" value={`${num(scenario.financial?.delta_mwh, 0)} MWh`} />
                    <Metric label="Cost increase" value={money(scenario.financial?.cost_delta_usd)}
                      tone="negative" detail="90% interval " testId="econ-cost" />
                    <Metric label="After-tax cost" value={money(scenario.financial?.after_tax_cost_usd)} />
                    <Metric label="Operating margin" value={bps(scenario.financial?.margin_delta)} tone="negative"
                      detail="change, no pass-through" />
                    <Metric label="Compiler" value={scenario.financial_compiler?.compiler?.replace('atlas.fec.', '') ?? 'FEC'}
                      detail={short(scenario.financial_compiler?.fingerprint, 10)} />
                  </div>
                  <div className="econ-intervals">
                    <span>Demand 90% parameter interval</span>
                    <strong>{pct(scenario.demand?.interval_90?.[0], 2)} → {pct(scenario.demand?.interval_90?.[1], 2)}</strong>
                    <span>Cost 90% interval</span>
                    <strong>{money(scenario.financial?.cost_interval_90?.[0])} → {money(scenario.financial?.cost_interval_90?.[1])}</strong>
                  </div>
                  <div className="econ-uncertainty">
                    {[
                      ['Observation', scenario.uncertainty?.observation?.note],
                      ['Parameters', `${scenario.uncertainty?.parameter?.draws} coefficient draws`],
                      ['Model form', `${scenario.uncertainty?.model_form?.alternatives?.length ?? 0} alternative form(s)`],
                      ['Relationship', 'not identified; no causal interval'],
                      ['Combined', 'deliberately suppressed'],
                    ].map(([label, detail]) => (
                      <div key={String(label)}><span>{label}</span><strong>{detail}</strong></div>
                    ))}
                  </div>
                  <p className="notice small">
                    The cost interval propagates coefficient parameter uncertainty only. It does not
                    pretend the observational relationship is identified or fold model-form uncertainty
                    into one confidence percentage.
                  </p>
                </div>
              )}
            </section>
          </div>

          {scenario && (
            <section className="card">
              <SectionHeader eyebrow="Sensitivity" title="Assumption changes move the financial result"
                detail="Each row recomputes the same central scenario through Atlas's compiler; none is an observed company sensitivity." />
              <div className="econ-sensitivity-grid">
                <div>
                  <h4>Temperature shock</h4>
                  <table className="mini-table"><thead><tr><th>°C</th><th>Demand</th><th>Cost</th></tr></thead>
                    <tbody>{(scenario.sensitivity?.temperature ?? []).map((row: Row) => (
                      <tr key={row.shock_c}><td className="mono">{num(row.shock_c, 1)}</td>
                        <td className="mono numeric">{pct(row.demand_change_fraction, 2)}</td>
                        <td className="mono numeric">{money(row.cost_delta_usd)}</td></tr>
                    ))}</tbody></table>
                </div>
                <div>
                  <h4>Power price</h4>
                  <table className="mini-table"><thead><tr><th>$/MWh</th><th>Cost</th></tr></thead>
                    <tbody>{(scenario.sensitivity?.power_price ?? []).map((row: Row) => (
                      <tr key={row.price_usd_mwh}><td className="mono">{money(row.price_usd_mwh)}</td>
                        <td className="mono numeric">{money(row.cost_delta_usd)}</td></tr>
                    ))}</tbody></table>
                </div>
                <div>
                  <h4>Unhedged exposure</h4>
                  <table className="mini-table"><thead><tr><th>Unhedged</th><th>Cost</th></tr></thead>
                    <tbody>{(scenario.sensitivity?.hedge ?? []).map((row: Row) => (
                      <tr key={row.hedge_fraction}><td className="mono">{pct(row.hedge_fraction, 0)}</td>
                        <td className="mono numeric">{money(row.cost_delta_usd)}</td></tr>
                    ))}</tbody></table>
                </div>
              </div>
            </section>
          )}
        </>
      )}

      <div className="split-2">
        <section className="card">
          <SectionHeader eyebrow="Temporal economic graph" title="Relationships with evidence classes"
            detail={`${graph?.counts?.entities ?? 0} entities · ${graph?.counts?.edges ?? 0} edges · ${graph?.counts?.observed_edges ?? 0} observed · ${graph?.counts?.hypothetical_edges ?? 0} hypothetical`}
            actions={<Badge tone="accent">Source-backed</Badge>} />
          <div className="table-wrap econ-graph-table">
            <table className="mini-table">
              <thead><tr><th>From</th><th>Relationship</th><th>To</th><th>Class</th></tr></thead>
              <tbody>{(graph?.edges ?? []).map((edge: Row) => (
                <tr key={edge.edge_id} title={`${edge.provenance}\n${edge.source_evidence}\nRights: ${edge.rights}`}>
                  <td>{edge.from_name}</td><td className="mono small">{edge.relationship_type.replaceAll('_', ' ')}</td>
                  <td>{edge.to_name}</td><td><Badge tone={edge.status === 'observed' ? 'positive' : edge.status === 'hypothetical' ? 'warn' : 'neutral'}>{edge.status}</Badge></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <p className="notice small">
            Hover an edge to inspect its source, note and rights. The company, facility and contractual
            edges are hypothetical and are never counted as observations.
          </p>
        </section>

        <section className="card" data-testid="econ-conflict">
          <SectionHeader eyebrow="Evidence reconciliation" title="Two stations disagree; both survive"
            detail={conflicts?.policy}
            actions={<Badge tone="warn">unresolved</Badge>} />
          {firstConflict ? (
            <>
              <div className="econ-conflict-head">
                <span className="mono small">{firstConflict.subject_key}</span>
                <span className="muted small">Detected {firstConflict.detected_at}</span>
              </div>
              <div className="econ-claim-grid">
                {(firstConflict.claims ?? []).map((claim: Row) => (
                  <div className="econ-claim" key={claim.claim_id}>
                    <div className="mono">{num(claim.value_numeric, 1)} {claim.unit}</div>
                    <div className="muted small">{claim.source_id} · {claim.epistemic_status}</div>
                    <div className="mono small">{claim.claim_id}</div>
                    <div className="muted small">Observed {claim.claimed_at}</div>
                  </div>
                ))}
              </div>
              <p className="notice small">{firstConflict.reason}. No automatic source wins; dependent research is marked stale, not rewritten.</p>
              <button className="button tiny-button" onClick={applyCorrection} disabled={busy !== null}>
                Record a 35.7 °C correction drill
              </button>
            </>
          ) : <div className="muted small">No contradictions detected in the current source set.</div>}
        </section>
      </div>

      <div className="split-2">
        <section className="card" data-testid="econ-sentinel">
          <SectionHeader eyebrow="Atlas Sentinel" title="Monitoring without automatic action"
            detail="Manual deterministic refresh; no scheduler is claimed."
            actions={<button className="button tiny-button" onClick={refreshSentinel} disabled={busy !== null}>Refresh sentinel</button>} />
          <div className="econ-sentinel-grid">
            <div><span>Fixture hash</span><strong className="mono">{short(sentinel?.source_freshness?.fixture_sha256_expected, 12)}</strong></div>
            <div><span>Latest period</span><strong>{sentinel?.source_freshness?.latest_period}</strong></div>
            <div><span>Dependencies</span><strong>{sentinel?.dependencies?.length ?? 0} observation keys</strong></div>
            <div><span>Stale runs</span><strong className={staleRuns.length ? 'negative' : ''}>{staleRuns.length}</strong></div>
          </div>
          {staleRuns.length > 0 && (
            <div className="banner banner-warn" style={{ marginTop: 10 }}>
              {staleRuns.map((item: Row) => <div key={item.run_id} className="small"><strong>{item.run_id}</strong> · {item.stale_reason}</div>)}
            </div>
          )}
          {(sentinel?.alerts ?? []).length > 0 ? (
            <div className="table-wrap" style={{ marginTop: 10 }}>
              <table className="mini-table"><thead><tr><th>Alert</th><th>Severity</th><th>Status</th></tr></thead>
                <tbody>{(sentinel?.alerts ?? []).map((alert: Row) => (
                  <tr key={alert.alert_id}><td>{alert.summary}</td><td>{alert.severity}</td><td>{alert.status}</td></tr>
                ))}</tbody></table>
            </div>
          ) : <p className="notice small" style={{ marginTop: 10 }}>No alerts. A correction drill will create a revision and invalidate dependent runs.</p>}
          <p className="notice small">Automatic retrain: {String(sentinel?.automatic_retrain)} · automatic deployment: {String(sentinel?.automatic_deployment)}</p>
        </section>

        <section className="card">
          <SectionHeader eyebrow="Historical replay" title="Refuse unsupported vintages"
            detail="Reconstruct only what the archive can legitimately support at the chosen cutoff."
            actions={<Badge tone="warn">No invented forecast</Badge>} />
          <div className="econ-replay-controls">
            <label>Cutoff date<input className="field mono" type="date" value={cutoff} onChange={(e) => setCutoff(e.target.value)} /></label>
            <button className="button" onClick={checkReplay} disabled={!run || busy !== null}>Check replay</button>
          </div>
          {replay && (
            <div className={`econ-replay-result ${replay.status === 'reproduced' ? 'is-ok' : 'is-blocked'}`} data-testid="econ-replay">
              <Badge tone={replay.status === 'reproduced' ? 'positive' : 'warn'}>{replay.status?.replaceAll('_', ' ')}</Badge>
              <p className="small">{replay.reason ?? replay.note}</p>
              {replay.rows && <div className="mono small">{replay.rows} rows · fingerprint {short(replay.reproduced_fingerprint, 12)}</div>}
              {!replay.reproduced && <div className="muted small">{replay.context?.fix}</div>}
            </div>
          )}
          <div className="econ-memory">
            <h4>Research memory</h4>
            <div className="muted small">{memory?.counts?.analyses ?? runs.length} analysis run(s) · {memory?.counts?.applications ?? 0} application(s) · retained failures and stale states</div>
            {runs.map((item: Row) => (
              <button className="lab-history-row" key={item.run_id} onClick={() => void openRun(item.run_id)}>
                <span><strong>{item.run_id}</strong><span className="muted small">{item.selected_model} · {item.conclusion?.replaceAll('_', ' ')}</span></span>
                <span className={`mono small ${item.stale ? 'negative' : 'muted'}`}>{item.stale ? 'stale' : num(item.test_rmse, 0)}</span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <section className="card econ-limitations">
        <SectionHeader eyebrow="Declared limits" title="What this application does not claim"
          detail="These limits travel with the saved application and its exports." />
        <div className="econ-limit-grid">
          {(run?.limitations ?? catalog?.limitations ?? []).map((item: string) => <div key={item}>{item}</div>)}
          <div>No facility-level company electricity contract, consumption schedule or supplier relationship is observed.</div>
          <div>No prediction-market, property-level, geopolitical or live-trading integration is implemented in Phase 7.</div>
          <div>The source archives are current downloads, not verified historical publication vintages.</div>
        </div>
      </section>
    </div>
  )
}
