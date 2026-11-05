import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Badge, SectionHeader } from '../components/ui'

type Row = Record<string, any>
const pct = (value: unknown, digits = 2) =>
  value == null ? '—' : `${(Number(value) * 100).toFixed(digits)}%`
const num = (value: unknown, digits = 4) =>
  value == null ? '—' : Number(value).toFixed(digits)
const money = (value: unknown) =>
  value == null ? '—' : `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`

function CurveSvg({ nodes }: { nodes: Row[] }) {
  if (!nodes.length) return null
  const width = 760
  const height = 180
  const pad = 20
  const values = nodes.map((node) => Number(node.zero_rate) * 100)
  const min = Math.min(...values) - 0.08
  const max = Math.max(...values) + 0.08
  const path = values
    .map((value, index) => {
      const x = pad + (index / (values.length - 1)) * (width - pad * 2)
      const y = height - pad - ((value - min) / (max - min || 1)) * (height - pad * 2)
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <svg className="inst-curve" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Zero-coupon yield curve">
      <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} className="lab-axis" />
      <path d={path} className="lab-line lab-line-accent" />
      {nodes.map((node, index) => {
        const x = pad + (index / (nodes.length - 1)) * (width - pad * 2)
        const y = height - pad - ((Number(node.zero_rate) * 100 - min) / (max - min || 1)) * (height - pad * 2)
        return <circle key={node.tenor} cx={x} cy={y} r={2.2} className="inst-dot" />
      })}
    </svg>
  )
}

function Tabs({ active, setActive }: { active: string; setActive: (value: string) => void }) {
  return (
    <div className="tabs" role="tablist" aria-label="Institutional research applications">
      {[
        ['fixed', 'Fixed income'],
        ['portfolio', 'Portfolio risk'],
        ['validation', 'Out-of-sample validation'],
      ].map(([key, label]) => (
        <button
          key={key}
          role="tab"
          aria-selected={active === key}
          className={`tab ${active === key ? 'is-active' : ''}`}
          onClick={() => setActive(key)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function Metric({ label, value, detail, tone, testId }: { label: string; value: string; detail?: string; tone?: string; testId?: string }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${tone ?? ''}`} data-testid={testId}>{value}</div>
      {detail && <div className="muted small">{detail}</div>}
    </div>
  )
}

export default function Institutional() {
  const [catalog, setCatalog] = useState<Row | null>(null)
  const [universe, setUniverse] = useState<Row | null>(null)
  const [applications, setApplications] = useState<Row[]>([])
  const [activeTab, setActiveTab] = useState('fixed')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState<string | null>(null)

  const [curveDate, setCurveDate] = useState('2024-06-28')
  const [curve, setCurve] = useState<Row | null>(null)
  const [settlement, setSettlement] = useState('2024-07-01')
  const [maturity, setMaturity] = useState('2029-06-30')
  const [coupon, setCoupon] = useState('4.25')
  const [face, setFace] = useState('100')
  const [bond, setBond] = useState<Row | null>(null)
  const [option, setOption] = useState<Row | null>(null)
  const [spot, setSpot] = useState('100')
  const [strike, setStrike] = useState('100')
  const [vol, setVol] = useState('20')
  const [time, setTime] = useState('1')
  const [rate, setRate] = useState('5')

  const [weights, setWeights] = useState<Record<string, string>>({})
  const [lookback, setLookback] = useState('252')
  const [maxWeight, setMaxWeight] = useState('60')
  const [cashWeight, setCashWeight] = useState('0')
  const [targetReturn, setTargetReturn] = useState('')
  const [risk, setRisk] = useState<Row | null>(null)
  const [optimized, setOptimized] = useState<Row | null>(null)
  const [validation, setValidation] = useState<Row | null>(null)
  const [opened, setOpened] = useState<Row | null>(null)
  const [compare, setCompare] = useState<Row[] | null>(null)

  useEffect(() => {
    Promise.all([api.institutionalCatalog(), api.institutionalUniverse(), api.institutionalApplications()])
      .then(([cat, universePayload, applicationPayload]) => {
        setCatalog(cat)
        setUniverse(universePayload)
        setApplications(applicationPayload.items)
        const instruments = (universePayload.instruments as Row[]).filter((item) => !item.delisted)
        setWeights(Object.fromEntries(instruments.map((item) => [item.security_id, (100 / instruments.length).toFixed(4)])))
      })
      .catch((caught: Error) => setError(caught.message))
  }, [])

  useEffect(() => {
    api.institutionalCurve(curveDate)
      .then(setCurve)
      .catch((caught: Error) => setError(caught.message))
  }, [curveDate])

  const instruments = useMemo(
    () => ((universe?.instruments ?? []) as Row[]).filter((item) => !item.delisted),
    [universe],
  )

  function riskWeights() {
    const values = Object.fromEntries(
      instruments.map((item) => [item.security_id, Number(weights[item.security_id] ?? 0) / 100]),
    )
    const total = Object.values(values).reduce(
      (sum: number, value) => sum + Number(value), 0,
    )
    if (total <= 0) throw new Error('Portfolio weights must sum to a positive value')
    return Object.fromEntries(Object.entries(values).map(([key, value]) => [key, Number(value) / total]))
  }

  async function runBond() {
    setLoading('bond'); setError(null); setMessage(null); setBond(null)
    try {
      const payload = await api.institutionalBond({
        curve_date: curveDate,
        settlement_date: settlement,
        maturity_date: maturity,
        coupon_rate: Number(coupon) / 100,
        face: Number(face),
      })
      setBond(payload)
      setMessage(`Bond priced · ${payload.run_id ?? 'not persisted'}`)
    } catch (caught) {
      setError((caught as Error).message)
    } finally { setLoading(null) }
  }

  async function runOption() {
    setLoading('option'); setError(null)
    try {
      setOption(await api.institutionalOption({
        spot: Number(spot), strike: Number(strike), time: Number(time),
        rate: Number(rate) / 100, volatility: Number(vol) / 100,
      }))
    } catch (caught) { setError((caught as Error).message) } finally { setLoading(null) }
  }

  async function runRisk() {
    setLoading('risk'); setError(null); setMessage(null)
    try {
      const payload = await api.institutionalPortfolio({
        weights: riskWeights(), lookback: Number(lookback), capital: 100000,
      })
      setRisk(payload)
      setMessage(`Risk computed · ${payload.run_id ?? 'not persisted'}`)
    } catch (caught) { setError((caught as Error).message) } finally { setLoading(null) }
  }

  async function runOptimize() {
    setLoading('optimize'); setError(null); setMessage(null)
    try {
      const payload = await api.institutionalOptimize({
        weights: riskWeights(), max_weight: Number(maxWeight) / 100,
        cash_weight: Number(cashWeight) / 100,
        target_return: targetReturn ? Number(targetReturn) / 100 : null,
      })
      setOptimized(payload)
      setMessage(payload.solution?.feasible ? 'Optimization solved' : `Infeasible: ${payload.solution?.reason}`)
    } catch (caught) { setError((caught as Error).message) } finally { setLoading(null) }
  }

  async function runValidation() {
    setLoading('validation'); setError(null); setMessage(null)
    try {
      const payload = await api.institutionalValidate({
        folds: 3, train: 252, validation: 63, test: 63, embargo: 5, step: 63,
        mode: 'rolling', lookbacks: [20, 60, 120], rebalance: 21, commission_bps: 2,
      })
      setValidation(payload)
      setMessage(`Walk-forward complete · ${payload.run_id ?? 'not persisted'}`)
      await refreshApplications()
    } catch (caught) { setError((caught as Error).message) } finally { setLoading(null) }
  }

  async function refreshApplications() {
    try {
      const payload = await api.institutionalApplications()
      setApplications(payload.items)
    } catch (caught) { setError((caught as Error).message) }
  }

  async function saveApplication(kind: 'fixed_income' | 'portfolio_risk' | 'optimization' | 'walk_forward') {
    setLoading('save'); setError(null)
    try {
      const isBond = kind === 'fixed_income'
      const result = isBond ? bond : kind === 'walk_forward' ? validation : kind === 'optimization' ? optimized : risk
      if (!result) throw new Error('Run the calculation before saving it')
      const inputs = isBond
        ? { curve_date: curveDate, settlement_date: settlement, maturity_date: maturity, coupon_rate: Number(coupon) / 100, face: Number(face) }
        : kind === 'walk_forward'
          ? { folds: 3, train: 252, validation: 63, test: 63, embargo: 5, lookbacks: [20, 60, 120] }
          : { weights: riskWeights(), lookback: Number(lookback), max_weight: Number(maxWeight) / 100, cash_weight: Number(cashWeight) / 100 }
      const payload = await api.institutionalApplication({
        kind,
        name: `${kind.replaceAll('_', ' ')} · ${new Date().toISOString()}`,
        inputs,
        result,
      })
      setMessage(`Saved application ${payload.object_id}`)
      await refreshApplications()
    } catch (caught) { setError((caught as Error).message) } finally { setLoading(null) }
  }

  async function openApplication(objectId: string) {
    setError(null)
    try {
      const object = await api.researchObject(objectId)
      const application = object.document?.spec?.application
      if (!application) throw new Error('Application has no stored inputs')
      setOpened(object)
      const inputs = application.inputs ?? {}
      if (application.type === 'fixed_income') {
        setCurveDate(inputs.curve_date ?? '2024-06-28')
        setSettlement(inputs.settlement_date ?? settlement)
        setMaturity(inputs.maturity_date ?? maturity)
        setCoupon(String((Number(inputs.coupon_rate) * 100).toFixed(4)))
        setFace(String(inputs.face ?? 100))
        setBond(application.result)
        setActiveTab('fixed')
      } else if (application.type === 'portfolio_risk') {
        setWeights(Object.fromEntries(Object.entries(inputs.weights ?? {}).map(([key, value]) => [key, (Number(value) * 100).toFixed(4)])))
        setRisk(application.result)
        setActiveTab('portfolio')
      } else if (application.type === 'optimization') {
        setOptimized(application.result)
        setActiveTab('portfolio')
      } else if (application.type === 'walk_forward') {
        setValidation(application.result)
        setActiveTab('validation')
      }
      setMessage(`Reopened ${object.name}`)
    } catch (caught) { setError((caught as Error).message) }
  }

  async function forkApplication() {
    if (!opened) return
    try {
      const forked = await api.forkResearchObject(opened.object_id, `${opened.name} fork ${Date.now()}`)
      setMessage(`Forked application ${forked.object_id}`)
      await refreshApplications()
    } catch (caught) { setError((caught as Error).message) }
  }

  async function compareApplications() {
    try {
      const ids = applications.slice(0, 2).map((item) => item.object_id)
      if (ids.length < 2) throw new Error('Save two applications first')
      const [left, right] = await Promise.all(ids.map((id) => api.researchObject(id)))
      setCompare([left, right])
    } catch (caught) { setError((caught as Error).message) }
  }

  async function exportOpened() {
    if (!opened) return
    try {
      const manifest = await api.exportResearchObject(opened.object_id)
      const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${opened.object_id}-institutional-manifest.json`
      anchor.click()
      URL.revokeObjectURL(url)
      setMessage('Exported the stored calculation manifest.')
    } catch (caught) { setError((caught as Error).message) }
  }

  return (
    <div className="page">
      <div className="section-header">
        <div>
          <div className="eyebrow">Quant Lab · Institutional research</div>
          <h1>Institutional research lab</h1>
          <p className="section-detail">
            Dated public curves, independently reconciled bond and option math, aligned portfolio risk,
            constrained optimization and walk-forward evaluation. The multi-asset fixture is explicitly synthetic.
          </p>
        </div>
        <div className="section-actions">
          <Link className="button" to="/lab">Back to strategy lab</Link>
          <Badge tone="synthetic">Synthetic portfolio</Badge>
          <Badge tone="accent">Public Treasury curve</Badge>
        </div>
      </div>

      <Tabs active={activeTab} setActive={setActiveTab} />
      {error && <div className="banner banner-warn error-text" data-testid="inst-error">{error}</div>}
      {message && <div className="banner banner-info" data-testid="inst-message">{message}</div>}

      {activeTab === 'fixed' && (
        <>
          <section className="card inst-controls">
            <div className="lab-field">
              <label htmlFor="curve-date">Treasury curve date</label>
              {(catalog?.curve?.dates?.length ?? 0) > 0 ? (
                <select id="curve-date" className="field" value={curveDate} onChange={(event) => setCurveDate(event.target.value)}>
                  {(catalog?.curve?.dates ?? []).map((item: string) => <option key={item} value={item}>{item}</option>)}
                </select>
              ) : <div className="field muted">Loading dates…</div>}
            </div>
            <div className="lab-field">
              <label htmlFor="settlement-date">Settlement</label>
              <input id="settlement-date" className="field mono" type="date" value={settlement} onChange={(event) => setSettlement(event.target.value)} />
            </div>
            <div className="lab-field">
              <label htmlFor="maturity-date">Maturity</label>
              <input id="maturity-date" className="field mono" type="date" value={maturity} onChange={(event) => setMaturity(event.target.value)} />
            </div>
            <div className="lab-field">
              <label htmlFor="coupon-rate">Coupon rate (%)</label>
              <input id="coupon-rate" className="field mono" type="number" step="0.01" value={coupon} onChange={(event) => setCoupon(event.target.value)} />
            </div>
            <div className="lab-field">
              <label htmlFor="face-value">Face value</label>
              <input id="face-value" className="field mono" type="number" value={face} onChange={(event) => setFace(event.target.value)} />
            </div>
            <button className="button button-primary" onClick={runBond} disabled={loading === 'bond'}>
              {loading === 'bond' ? 'Pricing…' : 'Calculate bond'}
            </button>
          </section>

          <div className="banner banner-info">
            <strong>Conventions.</strong> Treasury par yields are bootstrapped to continuous zero rates with a semiannual
            coupon convention; interpolation is linear in zero rates with flat extrapolation. The bond is hypothetical.
          </div>

          {curve && (
            <div className="split-2">
              <section className="card">
                <SectionHeader eyebrow="Dated market observation" title="Zero-coupon curve" detail={`${curve.observation_date} · ${curve.source.name}`} />
                <CurveSvg nodes={curve.nodes ?? []} />
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Tenor</th><th>Par</th><th>Zero</th><th>Discount</th></tr></thead>
                    <tbody>
                      {(curve.nodes ?? []).map((node: Row) => (
                        <tr key={node.tenor}>
                          <td>{node.tenor}</td>
                          <td className="mono numeric">{pct(node.par_yield, 3)}</td>
                          <td className="mono numeric">{pct(node.zero_rate, 3)}</td>
                          <td className="mono numeric">{num(node.discount_factor, 6)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="notice small mono break">{curve.source.sha256}</p>
              </section>
              <section className="card">
                <SectionHeader eyebrow="Provenance" title="What this curve is" />
                <div className="kv">
                  <dt>Source</dt><dd>{curve.source.name}</dd>
                  <dt>Public rights</dt><dd>{curve.source.rights}</dd>
                  <dt>Compounding</dt><dd>{curve.conventions.compounding}</dd>
                  <dt>Day count</dt><dd>{curve.conventions.day_count}</dd>
                  <dt>Bootstrap</dt><dd>{curve.conventions.bootstrap}</dd>
                  <dt>Adjustment</dt><dd>{curve.conventions.business_day_adjustment}</dd>
                </div>
                <ul className="lab-list">{(curve.limitations ?? []).map((item: string) => <li key={item}>{item}</li>)}</ul>
              </section>
            </div>
          )}

          {bond && (
            <>
              <div className="metric-grid">
                <Metric label="Clean price" value={num(bond.clean_price, 6)} detail={`dirty ${num(bond.dirty_price, 6)}`} testId="bond-clean-price" />
                <Metric label="Accrued interest" value={num(bond.accrued_interest, 6)} detail={`${bond.accrued_days}/${bond.coupon_period_days} days`} />
                <Metric label="Yield to maturity" value={pct(bond.yield_to_maturity, 4)} detail="nominal annual, semiannual" />
                <Metric label="Modified duration" value={num(bond.modified_duration, 4)} detail="years" />
                <Metric label="Convexity" value={num(bond.convexity, 4)} detail="cash-flow weighted" />
                <Metric label="DV01" value={`$${num(bond.dv01, 6)}`} detail="loss for +1bp parallel shift" testId="bond-dv01" />
              </div>
              <div className="split-2">
                <section className="card">
                  <SectionHeader eyebrow="Cash-flow schedule" title="Every coupon and principal" />
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead><tr><th>Date</th><th>Years</th><th>Coupon</th><th>Principal</th><th>Discount</th><th>PV</th></tr></thead>
                      <tbody>
                        {(bond.cash_flows ?? []).map((flow: Row) => (
                          <tr key={flow.date}>
                            <td className="mono">{flow.date}</td><td className="mono numeric">{num(flow.year_fraction, 4)}</td>
                            <td className="mono numeric">{num(flow.coupon, 4)}</td><td className="mono numeric">{num(flow.principal, 2)}</td>
                            <td className="mono numeric">{num(flow.discount_factor, 6)}</td><td className="mono numeric">{num(flow.present_value, 4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
                <section className="card">
                  <SectionHeader eyebrow="Rate shocks" title="Parallel zero-curve revaluation" />
                  <table className="mini-table">
                    <thead><tr><th>Shift</th><th>Dirty price</th><th>P&L / 100</th></tr></thead>
                    <tbody>
                      {(bond.shocks ?? []).map((item: Row) => (
                        <tr key={item.shift_bps}><td className="mono">{item.shift_bps > 0 ? '+' : ''}{item.shift_bps}bp</td>
                          <td className="mono numeric">{num(item.dirty_price, 5)}</td>
                          <td className={`mono numeric ${Number(item.pnl_per_100_face) >= 0 ? 'positive' : 'negative'}`}>{num(item.pnl_per_100_face, 5)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="notice small">DV01 identity: duration approximation ${num(bond.dv01_identity?.modified_duration_times_dirty_times_1bp, 6)} vs curve revaluation ${num(bond.dv01_identity?.curve_revaluation_dv01, 6)}.</p>
                  <div className="toolbar wrap" style={{ marginTop: 12 }}>
                    <button className="button" onClick={() => void saveApplication('fixed_income')} disabled={loading === 'save'}>Save fixed income</button>
                  </div>
                </section>
              </div>
            </>
          )}

          <section className="card">
            <SectionHeader eyebrow="Derivatives adapter" title="European option · Black-Scholes-Merton"
              detail="A theoretical model value, not an executable quote or a volatility-surface claim." />
            <div className="inst-option-controls">
              {[['Spot', spot, setSpot], ['Strike', strike, setStrike], ['Volatility (%)', vol, setVol], ['Rate (%)', rate, setRate], ['Years', time, setTime]].map(([label, value, setter]: any) => (
                <div className="lab-field" key={label}>
                  <label>{label}</label>
                  <input className="field mono" type="number" step="0.01" value={value} onChange={(event) => setter(event.target.value)} />
                </div>
              ))}
              <button className="button" onClick={runOption} disabled={loading === 'option'}>Price option</button>
            </div>
            {option && (
              <div className="split-2" style={{ marginTop: 14 }}>
                <table className="mini-table">
                  <thead><tr><th>Greek</th><th>Call</th><th>Put</th></tr></thead>
                  <tbody>
                    {['price', 'delta', 'gamma', 'vega', 'theta', 'rho'].map((key) => (
                      <tr key={key}><td>{key}</td><td className="mono numeric">{num(option.call?.[key], 6)}</td><td className="mono numeric">{num(option.put?.[key], 6)}</td></tr>
                    ))}
                  </tbody>
                </table>
                <div>
                  <p className="notice small">Put-call parity residual: <span className="mono">{num(option.parity_residual, 12)}</span></p>
                  <p className="notice small">Implied volatility call/put: {pct(option.implied_volatility?.call, 6)} / {pct(option.implied_volatility?.put, 6)}</p>
                </div>
              </div>
            )}
          </section>
        </>
      )}

      {activeTab === 'portfolio' && (
        <>
          <section className="card">
            <SectionHeader eyebrow="Synthetic multi-asset fixture" title="Portfolio weights"
              detail="Three active synthetic securities. The fourth path is delisted and is retained only as a coverage example." />
            <div className="inst-weight-grid">
              {instruments.map((item: Row) => (
                <div className="lab-field" key={item.security_id}>
                  <label htmlFor={`weight-${item.security_id}`}>{item.ticker} · {item.sector}</label>
                  <input id={`weight-${item.security_id}`} className="field mono" type="number" step="0.01"
                    value={weights[item.security_id] ?? ''} onChange={(event) => setWeights({ ...weights, [item.security_id]: event.target.value })} />
                </div>
              ))}
              <div className="lab-field"><label htmlFor="lookback">Lookback (sessions)</label>
                <input id="lookback" className="field mono" type="number" value={lookback} onChange={(event) => setLookback(event.target.value)} /></div>
              <div className="lab-field"><label htmlFor="max-weight">Max weight (%)</label>
                <input id="max-weight" className="field mono" type="number" value={maxWeight} onChange={(event) => setMaxWeight(event.target.value)} /></div>
              <div className="lab-field"><label htmlFor="cash-weight">Cash (%)</label>
                <input id="cash-weight" className="field mono" type="number" value={cashWeight} onChange={(event) => setCashWeight(event.target.value)} /></div>
              <div className="lab-field"><label htmlFor="target-return">Target return (%) optional</label>
                <input id="target-return" className="field mono" type="number" placeholder="estimate, not forecast" value={targetReturn} onChange={(event) => setTargetReturn(event.target.value)} /></div>
            </div>
            <div className="toolbar wrap" style={{ marginTop: 14 }}>
              <button className="button button-primary" onClick={runRisk} disabled={loading === 'risk'}>{loading === 'risk' ? 'Computing…' : 'Run risk'}</button>
              <button className="button" onClick={runOptimize} disabled={loading === 'optimize'}>Optimize portfolio</button>
              <button className="button" onClick={() => void saveApplication('portfolio_risk')} disabled={!risk || loading === 'save'}>Save risk</button>
              <button className="button" onClick={() => void saveApplication('optimization')} disabled={!optimized || loading === 'save'}>Save optimization</button>
            </div>
          </section>

          {risk && (
            <>
              <div className="metric-grid">
                <Metric label="Portfolio volatility" value={pct(risk.risk?.annualized_volatility)} detail={`${risk.lookback?.sessions} sessions`} testId="risk-vol" />
                <Metric label="Beta vs equal weight" value={num(risk.risk?.beta, 3)} detail="historical sample" />
                <Metric label="VaR 95%" value={pct(risk.risk?.historical_var_95_daily)} detail="daily historical loss" tone="negative" testId="risk-var" />
                <Metric label="Expected shortfall" value={pct(risk.risk?.historical_es_95_daily)} detail="daily tail average" tone="negative" />
                <Metric label="Max drawdown" value={pct(risk.risk?.max_drawdown)} detail="portfolio equity" tone="negative" />
                <Metric label="Gross / net" value={`${pct(risk.risk?.gross_exposure)} / ${pct(risk.risk?.net_exposure)}`} detail={`cash ${pct(risk.risk?.cash_exposure)}`} />
              </div>
              <div className="split-2">
                <section className="card">
                  <SectionHeader eyebrow="Risk decomposition" title="Who owns the variance" />
                  <table className="data-table">
                    <thead><tr><th>Security</th><th>Weight</th><th>Vol contribution</th><th>Variance share</th></tr></thead>
                    <tbody>
                      {(risk.securities ?? []).map((security: string) => (
                        <tr key={security}><td>{security}</td><td className="mono numeric">{pct(risk.weights?.[security])}</td>
                          <td className="mono numeric">{pct(risk.risk?.component_volatility?.[security])}</td>
                          <td className="mono numeric">{pct(risk.risk?.contribution_pct?.[security])}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="notice small">Contribution sum = {pct(risk.risk?.contribution_check?.sum_volatility_contributions)}; reconciliation {risk.risk?.contribution_check?.matches_portfolio_volatility ? 'passed' : 'failed'}.</p>
                </section>
                <section className="card">
                  <SectionHeader eyebrow="Stress testing" title="Declared linear scenarios" />
                  <table className="mini-table">
                    <thead><tr><th>Scenario</th><th>Return</th><th>P&L</th></tr></thead>
                    <tbody>
                      {(risk.stress_tests ?? []).map((scenario: Row) => (
                        <tr key={scenario.scenario}><td>{scenario.scenario.replaceAll('_', ' ')}<div className="muted small">{scenario.method}</div></td>
                          <td className="mono numeric">{pct(scenario.portfolio_return)}</td><td className="mono numeric">{money(scenario.pnl)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="notice small">Rate and volatility shocks are marked unsupported for this all-equity sleeve rather than assigned invented values.</p>
                </section>
              </div>
              <section className="card">
                <SectionHeader eyebrow="Sector exposure" title="Concentration by declared metadata" />
                <div className="inst-weight-grid">
                  {Object.entries(risk.risk?.sector_exposure ?? {}).map(([sector, value]) => (
                    <div key={sector} className="metric-card"><div className="metric-label">{sector}</div><div className="metric-value">{pct(value)}</div></div>
                  ))}
                </div>
              </section>
            </>
          )}

          {optimized && (
            <div className="split-2">
              <section className="card" data-testid="optimization-result">
                <SectionHeader eyebrow="Constrained optimization" title={optimized.solution?.feasible ? 'Feasible minimum-variance solution' : 'Infeasible problem'} />
                {optimized.solution?.feasible ? (
                  <table className="data-table">
                    <thead><tr><th>Security</th><th>Original</th><th>Optimized</th></tr></thead>
                    <tbody>
                      {(optimized.securities ?? []).map((security: string) => (
                        <tr key={security}><td>{security}</td><td className="mono numeric">{pct(optimized.original?.weights?.[security])}</td>
                          <td className="mono numeric">{pct(optimized.solution?.weights?.[security])}</td></tr>
                      ))}
                    </tbody>
                  </table>
                ) : <p className="notice">{optimized.solution?.reason}</p>}
                <p className="notice small">Solver: {optimized.solution?.solver ?? 'active-set KKT'}; expected returns are historical sample means, not forecasts.</p>
              </section>
              <section className="card">
                <SectionHeader eyebrow="Constraint audit" title="What the solver honored" />
                <div className="kv">
                  <dt>Sum</dt><dd>{pct(optimized.solution?.constraints?.sum_weights)}</dd>
                  <dt>Max weight</dt><dd>{pct(optimized.solution?.constraints?.max_weight)}</dd>
                  <dt>Long only</dt><dd>{optimized.solution?.constraints?.long_only ? 'yes' : 'no'}</dd>
                  <dt>Target</dt><dd>{optimized.solution?.constraints?.target_return_satisfied ? 'satisfied' : 'not requested / missed'}</dd>
                  <dt>Volatility</dt><dd>{pct(optimized.solution?.volatility)}</dd>
                </div>
                <ul className="lab-list">{(optimized.limitations ?? []).map((item: string) => <li key={item}>{item}</li>)}</ul>
              </section>
            </div>
          )}
        </>
      )}

      {activeTab === 'validation' && (
        <>
          <section className="card">
            <SectionHeader eyebrow="Out-of-sample research" title="Rolling walk-forward"
              detail="One parameter winner per family on train, family selected on validation, then a single untouched test evaluation." />
            <div className="toolbar wrap">
              <button className="button button-primary" onClick={runValidation} disabled={loading === 'validation'}>
                {loading === 'validation' ? 'Evaluating folds…' : 'Run walk-forward'}
              </button>
              <button className="button" onClick={() => void saveApplication('walk_forward')} disabled={!validation || loading === 'save'}>Save validation</button>
            </div>
          </section>
          {validation && (
            <>
              <div className="metric-grid" data-testid="validation-summary">
                <Metric label="OOS return" value={pct(validation.aggregate?.total_return)} detail={`${validation.aggregate?.observations} test sessions`} tone={Number(validation.aggregate?.total_return) >= 0 ? 'positive' : 'negative'} />
                <Metric label="Benchmark" value={pct(validation.aggregate?.benchmark_total_return)} detail="equal weight, zero cost" />
                <Metric label="OOS excess" value={pct(validation.aggregate?.excess_return)} detail="before significance" />
                <Metric label="OOS Sharpe" value={num(validation.aggregate?.sharpe, 2)} detail="test interval only" />
                <Metric label="Max drawdown" value={pct(validation.aggregate?.max_drawdown)} tone="negative" />
                <Metric label="Adjusted p-value" value={num(validation.multiple_testing?.adjusted_p_value, 3)} detail={`${validation.multiple_testing?.trials} attempts`} />
              </div>
              <div className="split-2">
                <section className="card">
                  <SectionHeader eyebrow="Folds" title="Frozen test intervals" />
                  <table className="data-table">
                    <thead><tr><th>Fold</th><th>Train</th><th>Validation</th><th>Test</th><th>Selected</th><th>Test return</th></tr></thead>
                    <tbody>
                      {(validation.folds ?? []).map((fold: Row) => (
                        <tr key={fold.fold}><td className="mono">{fold.fold}</td>
                          <td className="mono small">{fold.partitions.train.join(' → ')}</td>
                          <td className="mono small">{fold.partitions.validation.join(' → ')}</td>
                          <td className="mono small">{fold.partitions.test.join(' → ')}</td>
                          <td>{fold.selected_before_test.family} / {fold.selected_before_test.lookback}</td>
                          <td className={`mono numeric ${Number(fold.test_metrics?.total_return) >= 0 ? 'positive' : 'negative'}`}>{pct(fold.test_metrics?.total_return)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="notice small">Test used for selection: {validation.selection_policy?.test_used_for_selection ? 'yes' : 'no'} · folds completed: {validation.partitions?.folds_completed}.</p>
                </section>
                <section className="card">
                  <SectionHeader eyebrow="Stability and costs" title="Why not a proof of alpha" />
                  <div className="kv">
                    <dt>Families</dt><dd>{validation.parameter_stability?.unique_families?.join(', ')}</dd>
                    <dt>Lookbacks</dt><dd>{validation.parameter_stability?.unique_lookbacks?.join(', ')}</dd>
                    <dt>Same family</dt><dd>{validation.parameter_stability?.same_family_every_fold ? 'yes' : 'no'}</dd>
                    <dt>Data class</dt><dd>{validation.data_class}</dd>
                  </div>
                  <ul className="lab-list">{(validation.limitations ?? []).map((item: string) => <li key={item}>{item}</li>)}</ul>
                </section>
              </div>
              <section className="card">
                <SectionHeader eyebrow="Attempt log" title="Every candidate retained" detail="The losers are part of the evidence, not discarded chart decoration." />
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Fold</th><th>Stage</th><th>Family</th><th>Lookback</th><th>Return</th><th>Sharpe</th><th>Selected</th></tr></thead>
                    <tbody>
                      {(validation.attempts ?? []).slice(0, 60).map((attempt: Row, index: number) => (
                        <tr key={`${attempt.fold}-${attempt.stage}-${attempt.family}-${attempt.lookback}-${index}`}>
                          <td className="mono">{attempt.fold}</td><td>{attempt.stage}</td><td>{attempt.family}</td>
                          <td className="mono numeric">{attempt.lookback}</td><td className="mono numeric">{pct(attempt.metrics?.total_return)}</td>
                          <td className="mono numeric">{num(attempt.metrics?.sharpe, 2)}</td><td>{attempt.selected ? 'yes' : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </>
      )}

      <div className="split-2">
        <section className="card">
          <SectionHeader eyebrow="Saved institutional applications" title="Reopen, fork and export" detail={`${applications.length} application object(s)`} />
          <div className="lab-history">
            {applications.length === 0 && <div className="muted small">No saved institutional applications yet.</div>}
            {applications.slice(0, 10).map((application) => (
              <button key={application.object_id} className="lab-history-row" onClick={() => void openApplication(application.object_id)}>
                <span><strong>{application.name}</strong><span className="muted small">{application.object_id}</span></span>
                <span className="mono muted small">open</span>
              </button>
            ))}
          </div>
          <div className="toolbar wrap" style={{ marginTop: 12 }}>
            <button className="button" onClick={forkApplication} disabled={!opened}>Fork opened</button>
            <button className="button" onClick={exportOpened} disabled={!opened}>Export manifest</button>
            <button className="button" onClick={compareApplications} disabled={applications.length < 2}>Compare latest two</button>
          </div>
        </section>
        <section className="card">
          <SectionHeader eyebrow="Data rights and boundaries" title="What is actually supported" />
          <ul className="lab-list">
            <li>The curve is the official 2024 U.S. Treasury par-yield file; the exact bytes and SHA-256 are stored locally.</li>
            <li>The multi-asset panel is synthetic, with one delisted path. It is not a real market universe.</li>
            <li>IBM remains the only real security with price bars in this database.</li>
            <li>Bond terms are hypothetical; option values are model values, not executable quotes.</li>
            <li>Optimization does not support turnover or sector caps, and refuses them rather than ignoring them.</li>
          </ul>
          {compare && (
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table className="data-table">
                <thead><tr><th>Object</th><th>Name</th><th>Purpose</th><th>Hash</th></tr></thead>
                <tbody>{compare.map((item: Row) => (
                  <tr key={item.object_id}><td className="mono">{item.object_id}</td><td>{item.name}</td>
                    <td>{item.document?.spec?.purpose}</td><td className="mono small">{String(item.content_hash).slice(0, 12)}…</td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
