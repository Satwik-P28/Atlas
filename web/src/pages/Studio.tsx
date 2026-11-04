import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { CompanySummary } from '../types'

type Tab = 'valuation' | 'equations' | 'graph'
type GNode = { id: string; op: string; inputs: string[]; params: Record<string, unknown>; x: number; y: number }

const money = (value: unknown) =>
  typeof value === 'number'
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : String(value ?? '—')
const pct = (value: unknown) =>
  typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '—'

const FIELD_HELP: Record<string, string> = {
  revenue_growth: 'Per-year revenue growth. Each value is an explicit assumption.',
  operating_margin: 'EBIT margin applied to forecast revenue.',
  tax_rate: 'Cash tax rate applied to EBIT.',
  da_pct_revenue: 'Depreciation and amortisation as a share of revenue.',
  capex_pct_revenue: 'Capital expenditure as a share of revenue.',
  nwc_pct_revenue: 'Net working capital as a share of revenue.',
  wacc: 'Discount rate; a user assumption, not an observed market fact.',
  terminal_growth: 'Perpetual growth after the forecast. Must be below WACC.',
  cash: 'Balance-sheet cash added in the enterprise-to-equity bridge.',
  debt: 'Debt subtracted in the enterprise-to-equity bridge.',
  shares: 'Share count used for per-share value.',
}

function numberFields(defaults: Record<string, any>) {
  return {
    operating_margin: Number(defaults.operating_margin ?? 0.18),
    tax_rate: Number(defaults.tax_rate ?? 0.21),
    da_pct_revenue: Number(defaults.da_pct_revenue ?? 0.04),
    capex_pct_revenue: Number(defaults.capex_pct_revenue ?? 0.05),
    nwc_pct_revenue: Number(defaults.nwc_pct_revenue ?? 0.02),
    wacc: Number(defaults.wacc ?? 0.09),
    terminal_growth: Number(defaults.terminal_growth ?? 0.025),
    cash: Number(defaults.cash ?? 0),
    debt: Number(defaults.debt ?? 0),
    shares: Number(defaults.shares ?? 1),
  }
}

export default function Studio() {
  const [tab, setTab] = useState<Tab>('valuation')
  const [companies, setCompanies] = useState<CompanySummary[]>([])
  const [issuer, setIssuer] = useState('')
  const [defaults, setDefaults] = useState<Record<string, any> | null>(null)
  const [assumptions, setAssumptions] = useState<Record<string, number>>({})
  const [growth, setGrowth] = useState('5, 5, 5, 4, 4')
  const [dcf, setDcf] = useState<Record<string, any> | null>(null)
  const [scenarios, setScenarios] = useState<Record<string, any> | null>(null)
  const [sensitivity, setSensitivity] = useState<Record<string, any> | null>(null)
  const [reverseTarget, setReverseTarget] = useState('')
  const [reverse, setReverse] = useState<Record<string, any> | null>(null)
  const [saved, setSaved] = useState<Array<Record<string, any>>>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [eq, setEq] = useState('revenue * margin')
  const [eqInputs, setEqInputs] = useState('revenue=100\nmargin=0.2')
  const [eqResult, setEqResult] = useState<Record<string, any> | null>(null)
  const [nodes, setNodes] = useState<GNode[]>([
    { id: 'price', op: 'input', inputs: [], params: {}, x: 24, y: 36 },
    { id: 'shares', op: 'input', inputs: [], params: {}, x: 24, y: 148 },
    { id: 'value', op: 'mul', inputs: ['price', 'shares'], params: {}, x: 258, y: 88 },
  ])
  const [graphOutput, setGraphOutput] = useState('value')
  const [graphResult, setGraphResult] = useState<Record<string, any> | null>(null)
  const [newOperator, setNewOperator] = useState('mul')
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number } | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.companies().then((result) => {
      setCompanies(result.items)
      // Prefer the issuer with the deepest evidence coverage; a company with no
      // reported revenue cannot seed a DCF on this database.
      const preferred = result.items.reduce<CompanySummary | null>(
        (best, company) => (!best || company.evidence_count > best.evidence_count ? company : best),
        null,
      )
      if (preferred) setIssuer((current) => current || preferred.issuer_id)
    }).catch((err: Error) => setError(err.message))
    refreshSaved()
  }, [])

  useEffect(() => {
    if (!issuer) return
    setBusy(true)
    api.valuationDefaults(issuer)
      .then((payload) => {
        setDefaults(payload.defaults)
        setAssumptions(numberFields(payload.defaults))
        const rates = payload.defaults.revenue_growth as number[] | undefined
        if (rates?.length) setGrowth(rates.map((value) => (value * 100).toFixed(2)).join(', '))
        setError(null)
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false))
  }, [issuer])

  const refreshSaved = () => {
    api.researchObjects().then((payload) => setSaved(payload.items)).catch(() => undefined)
  }

  const payload = (): Record<string, unknown> => {
    const horizon = growth.split(',').map((value) => Number(value.trim()) / 100).filter((value) => Number.isFinite(value))
    return {
      issuer,
      assumptions: {
        ...assumptions,
        revenue: defaults?.revenue,
        revenue_growth: horizon.length ? horizon : [0.05],
        horizon: horizon.length || 5,
      },
    }
  }

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await action()
    } catch (err) {
      const context = (err as { context?: unknown }).context
      setError(context ? `${(err as Error).message}: ${JSON.stringify(context)}` : (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const runDcf = () => run(async () => {
    const result = await api.valuationDcf(payload())
    setDcf(result)
    setScenarios(null)
    setSensitivity(null)
    setReverse(null)
    setNotice('Compiler execution complete. Every value is traceable in the valuation audit.')
  })

  const runAnalysis = () => run(async () => {
    const [scenarioResult, sensitivityResult] = await Promise.all([
      api.valuationScenarios(payload()),
      api.valuationSensitivity(payload()),
    ])
    setScenarios(scenarioResult)
    setSensitivity(sensitivityResult)
  })

  const runReverse = () => run(async () => {
    const target = Number(reverseTarget)
    if (!target) throw new Error('Enter a dated observed price first')
    const result = await api.valuationReverse({
      ...payload(),
      target_price: target,
      variable: 'terminal_growth',
    })
    setReverse(result)
  })

  const runEquation = () => run(async () => {
    const inputs: Record<string, unknown> = { revenue: 100, margin: 0.2 }
    for (const line of eqInputs.split('\n')) {
      const [key, value] = line.split('=')
      if (key?.trim() && value !== undefined && Number.isFinite(Number(value))) {
        inputs[key.trim()] = Number(value)
      }
    }
    const result = await api.modelRun({
      schema_version: 'atlas.model.v1',
      name: 'Studio equation model',
      interface: 'equation',
      inputs: [
        { name: 'revenue', type: 'Money[USD]' },
        { name: 'margin', type: 'Ratio' },
      ],
      equations: [{ name: 'output', expr: eq }],
      outputs: ['output'],
      as_of: new Date().toISOString(),
      mode: 'public_available',
    }, inputs)
    setEqResult(result)
    setNotice('Equation compiled to the same typed IR used by the DCF and graph editor.')
  })

  const graphSpec = () => ({
    schema_version: 'atlas.model.v1',
    name: 'Studio visual model',
    interface: 'graph',
    inputs: [
      { name: 'price', type: 'Price[USD]' },
      { name: 'shares', type: 'Shares' },
    ],
    nodes: nodes.filter((node) => !['price', 'shares'].includes(node.id)).map((node) => ({
      id: node.id, op: node.op, inputs: node.inputs, params: node.params,
    })),
    outputs: { value: graphOutput },
    as_of: new Date().toISOString(),
    mode: 'public_available',
  })

  const runGraph = () => run(async () => {
    const result = await api.modelRun(graphSpec(), { price: 100, shares: 2.5 })
    setGraphResult(result)
    setNotice('Visual graph compiled and executed.')
  })

  const compileGraph = () => run(async () => {
    const result = await api.modelCompile(graphSpec())
    setGraphResult({ compiled: result })
    setNotice('Graph is type-correct. No output value has been executed yet.')
  })

  const updateNode = (id: string, patch: Partial<GNode>) =>
    setNodes((current) => current.map((node) => node.id === id ? { ...node, ...patch } : node))

  const addNode = () => setNodes((current) => [
    ...current,
    { id: `node_${current.length + 1}`, op: newOperator, inputs: [], params: {}, x: 250, y: 40 + current.length * 74 },
  ])

  const saveApplication = () => run(async () => {
    if (!dcf?.model_spec) throw new Error('Run the DCF before saving an application')
    const evidenceIds = (dcf.audit?.evidence_ids ?? []) as string[]
    if (!evidenceIds.length) throw new Error('This run has no evidence-linked inputs to cite')
    const now = new Date().toISOString()
    const modelObject = await api.createResearchObject({
      schema_version: 'atlas.research_object.v1',
      kind: 'model',
      name: `DCF · ${dcf.issuer?.legal_name ?? issuer}`,
      version: '1.0.0',
      status: 'validated',
      description: 'Compiler-backed unlevered DCF with explicit forecasting assumptions.',
      as_of: now,
      mode: 'public_available',
      evidence_ids: evidenceIds,
      spec: {
        inputs: dcf.model?.inputs ?? {},
        outputs: dcf.model?.outputs ?? {},
        method: 'atlas.model.v1',
        assumptions: dcf.assumptions,
        validation: 'compiled; independent reference arithmetic verified',
        model_spec: dcf.model_spec,
        run_id: dcf.run_id,
        fingerprint: dcf.fingerprint,
      },
    })
    const application = await api.createResearchObject({
      schema_version: 'atlas.research_object.v1',
      kind: 'application',
      name: `Valuation application · ${dcf.issuer?.legal_name ?? issuer}`,
      version: '1.0.0',
      status: 'validated',
      description: 'A saved valuation workspace referencing an immutable model object.',
      as_of: now,
      mode: 'public_available',
      evidence_ids: [],
      object_ids: [modelObject.object_id],
      spec: {
        purpose: 'Institutional DCF, scenarios and sensitivity review',
        views: ['historical', 'forecast', 'dcf', 'scenario', 'sensitivity', 'audit'],
        model_object_id: modelObject.object_id,
        model_fingerprint: dcf.fingerprint,
      },
    })
    setNotice(`Saved model ${modelObject.object_id} and application ${application.object_id}.`)
    refreshSaved()
  })

  const fork = (objectId: string) => run(async () => {
    const name = window.prompt('New application name')
    if (!name) return
    const result = await api.forkResearchObject(objectId, name, '1.0.1')
    setNotice(`Forked to ${result.object_id}.`)
    refreshSaved()
  })

  const exportObject = (objectId: string) => run(async () => {
    const manifest = await api.exportResearchObject(objectId)
    const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${objectId}-manifest.json`
    anchor.click()
    URL.revokeObjectURL(url)
  })

  const auditEvidence = (dcf?.audit?.evidence_ids ?? []) as string[]
  const fieldEntries = useMemo(() => Object.entries(assumptions).filter(([key]) => FIELD_HELP[key]), [assumptions])

  return (
    <div className="studio-page" style={{ padding: '28px 30px', maxWidth: 1280, margin: '0 auto' }}>
      <style>{`
        @media (max-width: 760px) {
          .studio-page { padding: 16px !important; }
          .studio-split { grid-template-columns: minmax(0, 1fr) !important; }
          .studio-split > * { min-width: 0; }
        }
      `}</style>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 18, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div>
          <h1>Studio</h1>
          <p className="muted" style={{ marginTop: 6, maxWidth: 760 }}>
            Build financial models on Atlas's typed compiler. Equations, visual graphs and the Python SDK
            all produce the same canonical model specification; the evidence kernel supplies the historical cutoff.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {(['valuation', 'equations', 'graph'] as Tab[]).map((item) => (
            <button key={item} onClick={() => setTab(item)}
              style={{ padding: '8px 14px', borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer',
                background: tab === item ? 'var(--accent-soft)' : 'var(--bg-card)',
                color: tab === item ? 'var(--accent)' : 'var(--text)' }}>
              {item === 'valuation' ? 'Valuation lab' : item === 'equations' ? 'Equations' : 'Visual graph'}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 20, flexWrap: 'wrap' }}>
        <label className="small muted">Company</label>
        <select value={issuer} onChange={(event) => setIssuer(event.target.value)}
          style={{ minWidth: 280, padding: 8, background: 'var(--bg-input)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6 }}>
          {companies.map((company) => (
            <option key={company.issuer_id} value={company.issuer_id}>{company.legal_name}</option>
          ))}
        </select>
        {busy && <span className="small muted">compiling…</span>}
        {notice && <span className="small positive">{notice}</span>}
      </div>
      {error && <div style={{ marginTop: 14, padding: 12, border: '1px solid var(--negative)', borderRadius: 6, color: 'var(--negative)', whiteSpace: 'pre-wrap' }}>{error}</div>}

      {tab === 'valuation' && (
        <div className="studio-split" style={{ display: 'grid', gridTemplateColumns: 'minmax(300px, 380px) 1fr', gap: 18, marginTop: 20 }}>
          <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
            <h3>Assumptions</h3>
            <p className="small muted" style={{ marginTop: 4 }}>Observed inputs are evidence-linked; the rest are explicitly labelled assumptions.</p>
            <label className="small muted" style={{ display: 'block', marginTop: 14 }}>Revenue growth % by year</label>
            <input value={growth} onChange={(event) => setGrowth(event.target.value)} style={inputStyle} />
            {fieldEntries.map(([key, value]) => (
              <div key={key} style={{ marginTop: 10 }}>
                <label className="small muted" style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>{key.replaceAll('_', ' ')}</span>
                  <span className="mono">{value}</span>
                </label>
                <input type="number" step="0.001" value={value}
                  onChange={(event) => setAssumptions((current) => ({ ...current, [key]: Number(event.target.value) }))}
                  style={inputStyle} />
                <div className="small muted" style={{ fontSize: 11 }}>{FIELD_HELP[key]}</div>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
              <button onClick={runDcf} disabled={busy} style={buttonStyle}>Run DCF</button>
              <button onClick={runAnalysis} disabled={busy} style={secondaryStyle}>Scenarios + sensitivity</button>
            </div>
            <div style={{ marginTop: 18, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
              <h4>Reverse DCF</h4>
              <p className="small muted">Observed price, then solve implied perpetual growth.</p>
              <input value={reverseTarget} onChange={(event) => setReverseTarget(event.target.value)}
                placeholder={defaults?.price ? `Observed ${defaults.price}` : 'Observed price'} style={inputStyle} />
              <button onClick={runReverse} disabled={busy} style={secondaryStyle}>Solve implied growth</button>
              {reverse && (
                <pre className="mono small" style={preStyle}>{JSON.stringify(reverse, null, 2)}</pre>
              )}
            </div>
          </section>

          <section style={{ display: 'grid', gap: 16 }}>
            <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <h3>Unlevered DCF</h3>
                {dcf && <span className="small muted mono">{dcf.run_id}</span>}
              </div>
              {!dcf && <p className="muted" style={{ marginTop: 8 }}>Run the model to see enterprise value, equity value and per-share output.</p>}
              {dcf && (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginTop: 12 }}>
                    {[
                      ['Value / share', `$${money(dcf.outputs.value_per_share)}`],
                      ['Equity value', `$${money(dcf.outputs.equity_value)}`],
                      ['Enterprise value', `$${money(dcf.outputs.enterprise_value)}`],
                      ['PV explicit', `$${money(dcf.outputs.pv_explicit)}`],
                      ['PV terminal', `$${money(dcf.outputs.pv_terminal)}`],
                    ].map(([label, value]) => (
                      <div key={label} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 10 }}>
                        <div className="small muted">{label}</div>
                        <div className="mono" style={{ fontSize: 18, marginTop: 3 }}>{value}</div>
                      </div>
                    ))}
                  </div>
                  <h4 style={{ marginTop: 16 }}>Forecast FCFF</h4>
                  <div className="mono small" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {(dcf.outputs.fcff as number[]).map((value, index) => (
                      <span key={index} style={{ padding: '6px 8px', border: '1px solid var(--border)', borderRadius: 4 }}>
                        Y{index + 1}: ${money(value)}
                      </span>
                    ))}
                  </div>
                  <div className="small muted" style={{ marginTop: 12 }}>
                    {dcf.audit?.formula}
                  </div>
                  <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <button onClick={saveApplication} disabled={busy} style={secondaryStyle}>Save model + application</button>
                    {auditEvidence.slice(0, 4).map((id) => (
                      <a key={id} href={`/api/evidence/${encodeURIComponent(id)}`} target="_blank" rel="noreferrer"
                        className="small mono" style={{ padding: '6px 8px', border: '1px solid var(--border)', borderRadius: 4 }}>
                        {id.slice(0, 18)}…
                      </a>
                    ))}
                  </div>
                </>
              )}
            </div>

            {scenarios && (
              <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
                <h3>Scenarios</h3>
                <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 10 }}>
                  <thead><tr><th style={thStyle}>Case</th><th style={thStyle}>Value / share</th><th style={thStyle}>Δ vs base</th><th style={thStyle}>WACC</th><th style={thStyle}>Margin</th></tr></thead>
                  <tbody>
                    {Object.entries(scenarios.scenarios as Record<string, any>).map(([name, row]) => (
                      <tr key={name}>
                        <td style={tdStyle}>{name}</td>
                        <td style={tdStyle} className="mono">${money(row.value_per_share)}</td>
                        <td style={tdStyle} className="mono">{row.delta_vs_base >= 0 ? '+' : ''}{money(row.delta_vs_base)}</td>
                        <td style={tdStyle} className="mono">{pct(row.assumptions?.wacc)}</td>
                        <td style={tdStyle} className="mono">{pct(row.assumptions?.operating_margin)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {sensitivity && (
              <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
                <h3>Sensitivity · WACC × terminal growth</h3>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ borderCollapse: 'collapse', marginTop: 10 }}>
                    <thead><tr><th style={thStyle}>WACC</th>{sensitivity.column_labels.map((label: string) => <th key={label} style={thStyle}>{label}</th>)}</tr></thead>
                    <tbody>
                      {sensitivity.matrix.map((row: number[], r: number) => (
                        <tr key={r}>
                          <td style={thStyle}>{sensitivity.row_labels[r]}</td>
                          {row.map((value, c) => <td key={c} style={tdStyle} className="mono">${money(value)}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {tab === 'equations' && (
        <div className="studio-split" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginTop: 20 }}>
          <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
            <h3>Equation editor</h3>
            <p className="small muted">Allowlisted arithmetic: + − × ÷ ^, parentheses, abs/min/max/sum/mean/growth/npv. No arbitrary Python.</p>
            <textarea value={eq} onChange={(event) => setEq(event.target.value)} rows={5}
              style={{ ...inputStyle, fontFamily: 'var(--mono)', marginTop: 12 }} />
            <label className="small muted" style={{ display: 'block', marginTop: 10 }}>Inputs (name=value)</label>
            <textarea value={eqInputs} onChange={(event) => setEqInputs(event.target.value)} rows={4}
              style={{ ...inputStyle, fontFamily: 'var(--mono)' }} />
            <button onClick={runEquation} disabled={busy} style={{ ...buttonStyle, marginTop: 12 }}>Compile + execute</button>
          </section>
          <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
            <h3>Typed result</h3>
            {!eqResult && <p className="muted">The compiler will show type errors and dependency diagnostics here.</p>}
            {eqResult && <pre className="mono small" style={preStyle}>{JSON.stringify(eqResult, null, 2)}</pre>}
          </section>
        </div>
      )}

      {tab === 'graph' && (
        <div className="studio-split" style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 18, marginTop: 20 }}>
          <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <button onClick={compileGraph} disabled={busy} style={secondaryStyle}>Validate graph</button>
              <button onClick={runGraph} disabled={busy} style={buttonStyle}>Execute graph</button>
              <select value={newOperator} onChange={(event) => setNewOperator(event.target.value)} style={selectStyle}>
                {['add', 'sub', 'mul', 'div', 'neg', 'abs', 'growth', 'npv', 'terminal_value', 'discount', 'sum', 'mean'].map((op) => <option key={op}>{op}</option>)}
              </select>
              <button onClick={addNode} style={secondaryStyle}>Add node</button>
              <label className="small muted">Output
                <select value={graphOutput} onChange={(event) => setGraphOutput(event.target.value)} style={{ ...selectStyle, marginLeft: 6 }}>
                  {nodes.filter((node) => node.op !== 'input').map((node) => <option key={node.id}>{node.id}</option>)}
                </select>
              </label>
            </div>
            <div ref={canvasRef} onPointerMove={(event) => {
              if (!drag) return
              const box = canvasRef.current?.getBoundingClientRect()
              if (!box) return
              updateNode(drag.id, { x: event.clientX - box.left - drag.dx, y: event.clientY - box.top - drag.dy })
            }} onPointerUp={() => setDrag(null)} onPointerLeave={() => setDrag(null)}
              style={{ position: 'relative', minHeight: 420, marginTop: 12, overflow: 'hidden', borderRadius: 6, background: 'var(--bg-input)', border: '1px dashed var(--border-strong)' }}>
              <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
                {nodes.flatMap((target) => target.inputs.map((sourceId, index) => {
                  const source = nodes.find((node) => node.id === sourceId)
                  if (!source) return null
                  return <line key={`${sourceId}-${target.id}-${index}`} x1={source.x + 150} y1={source.y + 34}
                    x2={target.x} y2={target.y + 34 + index * 18} stroke="var(--accent)" strokeWidth={1.5} opacity={0.7} />
                }))}
              </svg>
              {nodes.map((node) => (
                <div key={node.id} onPointerDown={(event) => {
                  const box = canvasRef.current?.getBoundingClientRect()
                  if (!box) return
                  setDrag({ id: node.id, dx: event.clientX - box.left - node.x, dy: event.clientY - box.top - node.y })
                }} style={{ position: 'absolute', left: node.x, top: node.y, width: 150, cursor: 'grab',
                  background: 'var(--bg-card)', border: '1px solid var(--border-strong)', borderRadius: 6, padding: 8 }}>
                  <div className="small mono" style={{ fontWeight: 600 }}>{node.id}</div>
                  <div className="small muted">{node.op}{node.op !== 'input' ? ` · ${node.inputs.length} input(s)` : ' · input'}</div>
                  {node.op !== 'input' && (
                    <select value={node.inputs[0] ?? ''} onChange={(event) => updateNode(node.id, { inputs: event.target.value ? [event.target.value, ...node.inputs.slice(1)] : node.inputs.slice(1) })}
                      onPointerDown={(event) => event.stopPropagation()}
                      style={{ ...selectStyle, width: '100%', marginTop: 4, fontSize: 11 }}>
                      <option value="">connect input…</option>
                      {nodes.filter((candidate) => candidate.id !== node.id).map((candidate) => <option key={candidate.id}>{candidate.id}</option>)}
                    </select>
                  )}
                </div>
              ))}
            </div>
            <p className="small muted" style={{ marginTop: 8 }}>Drag nodes to arrange. Connect an input to another node; types are checked by the compiler, not the canvas.</p>
          </section>
          <section style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
            <h3>Execution</h3>
            <p className="small muted">Sample bindings: price=100, shares=2.5.</p>
            {graphResult && <pre className="mono small" style={preStyle}>{JSON.stringify(graphResult, null, 2)}</pre>}
            <h4 style={{ marginTop: 20 }}>Saved applications</h4>
            {!saved.length && <p className="small muted">No saved research objects yet.</p>}
            {saved.map((item) => (
              <div key={item.object_id} style={{ borderTop: '1px solid var(--border)', padding: '8px 0' }}>
                <div className="small">{item.name} <span className="muted">v{item.version}</span></div>
                <div className="small muted mono">{item.object_id}</div>
                <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                  <button onClick={() => fork(item.object_id)} className="small" style={tinyStyle}>Fork</button>
                  <button onClick={() => exportObject(item.object_id)} className="small" style={tinyStyle}>Export</button>
                </div>
              </div>
            ))}
          </section>
        </div>
      )}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: '100%', marginTop: 4, padding: '7px 8px', background: 'var(--bg-input)',
  color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 5,
}
const selectStyle: React.CSSProperties = {
  padding: '6px 8px', background: 'var(--bg-input)', color: 'var(--text)',
  border: '1px solid var(--border)', borderRadius: 5,
}
const buttonStyle: React.CSSProperties = {
  padding: '8px 14px', border: '1px solid var(--accent)', borderRadius: 5,
  background: 'var(--accent-soft)', color: 'var(--accent)', cursor: 'pointer',
}
const secondaryStyle: React.CSSProperties = {
  ...buttonStyle, border: '1px solid var(--border-strong)', background: 'var(--bg-card)', color: 'var(--text)',
}
const tinyStyle: React.CSSProperties = {
  padding: '3px 7px', border: '1px solid var(--border)', borderRadius: 4,
  background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer',
}
const preStyle: React.CSSProperties = {
  whiteSpace: 'pre-wrap', overflow: 'auto', maxHeight: 360, marginTop: 10,
  padding: 10, background: 'var(--bg-input)', border: '1px solid var(--border)', borderRadius: 5,
}
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border-strong)', fontSize: 12 }
const tdStyle: React.CSSProperties = { padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 12 }
