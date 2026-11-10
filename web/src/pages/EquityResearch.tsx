import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import '../equity.css'
import ObservationProvenance from '../components/ObservationProvenance'
import { Badge, EmptyState, ErrorState, Loading, SectionHeader } from '../components/ui'

type Row = Record<string, any>

const num = (value: unknown, digits = 2) =>
  value == null ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits })

const money = (value: unknown) => {
  if (value == null) return '—'
  const number = Number(value)
  const absolute = Math.abs(number)
  if (absolute >= 1e12) return `${(number / 1e12).toFixed(2)}T`
  if (absolute >= 1e9) return `${(number / 1e9).toFixed(2)}B`
  if (absolute >= 1e6) return `${(number / 1e6).toFixed(2)}M`
  return number.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

const pct = (value: unknown, digits = 2) =>
  value == null ? '—' : `${(Number(value) * 100).toFixed(digits)}%`

const eligibilityTone = (status: string) =>
  status === 'eligible' ? 'positive' : status === 'unsupported_methodology' ? 'negative' : 'warn'

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export default function EquityResearch() {
  const [coverage, setCoverage] = useState<Row | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [workspace, setWorkspace] = useState<Row | null>(null)
  const [report, setReport] = useState<Row | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [regulatory, setRegulatory] = useState<Row | null>(null)
  const [roe, setRoe] = useState('')
  const [coe, setCoe] = useState('')
  const [cutoff, setCutoff] = useState('')
  const [priceCsv, setPriceCsv] = useState('')
  const [saved, setSaved] = useState<Row[]>([])
  const [savedRevision, setSavedRevision] = useState(0)
  const [memo, setMemo] = useState<Row | null>(null)
  const [memoSaved, setMemoSaved] = useState<Row | null>(null)
  const [memoChange, setMemoChange] = useState<Row | null>(null)

  useEffect(() => {
    api
      .equityCoverage()
      .then((payload) => {
        setCoverage(payload)
        const items: Row[] = payload.items ?? []
        if (items.length) setSelected(items[0].issuer_id)
      })
      .catch((caught: Error) => setError(caught.message))
  }, [])

  useEffect(() => {
    if (!selected) return
    setWorkspace(null)
    setReport(null)
    setMessage(null)
    api
      .equityWorkspace(selected, { mode: 'public_available' })
      .then(setWorkspace)
      .catch((caught: Error) => setError(caught.message))
    api
      .equityRegulatory(selected)
      .then(setRegulatory)
      .catch(() => setRegulatory(null))
  }, [selected])

  useEffect(() => {
    let cancelled = false
    if (!selected) {
      setSaved([])
      return
    }
    async function loadSaved() {
      try {
        const payload = await api.researchObjects('application')
        const items: Row[] = []
        for (const summary of payload.items ?? []) {
          try {
            const object = await api.researchObject(summary.object_id)
            const application = object.document?.spec?.application
            if (application?.type === 'equity_research' && application?.identifier === selected) {
              items.push({ ...summary, document: object.document })
            }
          } catch {
            // A removed or unreadable object must not prevent the research page from loading.
          }
        }
        if (!cancelled) setSaved(items)
      } catch {
        if (!cancelled) setSaved([])
      }
    }
    loadSaved()
    return () => { cancelled = true }
  }, [selected, savedRevision])

  const row = useMemo<Row | null>(() => {
    const items: Row[] = coverage?.items ?? []
    return items.find((item) => item.issuer_id === selected) ?? null
  }, [coverage, selected])

  async function generate() {
    if (!selected) return
    setBusy('report')
    setError(null)
    setMessage(null)
    try {
      const assumptions: Row = {}
      if (roe.trim()) assumptions.sustainable_roe = Number(roe) / 100
      if (coe.trim()) assumptions.cost_of_equity = Number(coe) / 100
      const built = await api.equityReport(selected, {
        assumptions,
        as_of: cutoff || undefined,
      })
      setReport(built)
      setMessage(
        `Report ${built.metadata?.report_sha256?.slice(0, 16) ?? ''}… · valuation ${
          built.valuation?.status ?? 'unknown'
        } · audit ${built.valuation?.audit?.verdict ?? 'n/a'}`,
      )
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function applyCutoff() {
    if (!selected) return
    setBusy('cutoff')
    setError(null)
    try {
      setWorkspace(await api.equityWorkspace(selected, { mode: 'public_available', asOf: cutoff || undefined }))
      setMessage(cutoff ? `Information cutoff set to ${cutoff}. Unavailable observations are excluded.` : 'Using the latest available observations.')
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function rejectDcf() {
    if (!selected) return
    setBusy('reject')
    setError(null)
    try {
      const assumptions: Row = {}
      if (roe.trim()) assumptions.sustainable_roe = Number(roe) / 100
      if (coe.trim()) assumptions.cost_of_equity = Number(coe) / 100
      const built = await api.equityReport(selected, {
        assumptions,
        method: 'unlevered_fcff_dcf',
        as_of: cutoff || undefined,
      })
      setReport(built)
      setMessage(`FCFF DCF request: ${built.valuation?.status}. ${built.valuation?.reason ?? ''}`)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function importPrices() {
    if (!selected || !priceCsv.trim()) return
    setBusy('prices')
    setError(null)
    try {
      const lines = priceCsv.trim().split(/\r?\n/).filter(Boolean)
      const hasHeader = lines[0].toLowerCase().includes('date')
      const rows = lines.slice(hasHeader ? 1 : 0).map((line) => {
        const [date, open, high, low, close, volume] = line.split(',').map((cell) => cell.trim())
        return { date, open: Number(open), high: Number(high), low: Number(low), close: Number(close), volume: Number(volume || 0) }
      })
      const imported = await api.equityPriceImport(selected, {
        rows,
        source_name: 'Nasdaq quote history (user import)',
        licence: 'Provider terms; local analysis only',
        redistribution: 'restricted',
        adjustment_semantics: 'unadjusted',
      })
      setMessage(`Imported ${imported.import?.written ?? 0} observations. Export allowed: ${imported.import?.source?.export_allowed ? 'yes' : 'no (restricted)'}.`)
      setWorkspace(await api.equityWorkspace(selected, { mode: 'public_available', asOf: cutoff || undefined }))
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  function memoAssumptions(): Row {
    const assumptions: Row = {}
    if (roe.trim()) assumptions.sustainable_roe = Number(roe) / 100
    if (coe.trim()) assumptions.cost_of_equity = Number(coe) / 100
    return assumptions
  }

  async function createMemo() {
    if (!selected) return
    setBusy('memo')
    setError(null)
    try {
      const built = await api.equityMemo(selected, {
        assumptions: memoAssumptions(),
        as_of: cutoff || undefined,
        method: report?.valuation?.method ?? undefined,
      })
      setMemo(built)
      setMemoSaved(null)
      setMemoChange(null)
      setMessage(
        `Research memo built · ${built.claims?.length ?? 0} claims · hash ${String(built.content_hash ?? '').slice(0, 12)}…`,
      )
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function saveMemo() {
    if (!selected || !memo) {
      setError('Build the memo before saving it.')
      return
    }
    setBusy('memo-save')
    setError(null)
    try {
      const savedMemo = await api.equityMemoSave(selected, {
        assumptions: memoAssumptions(),
        as_of: cutoff || undefined,
        method: report?.valuation?.method ?? undefined,
      })
      setMemoSaved(savedMemo)
      setMessage(`Saved memo ${savedMemo.object_id} v${savedMemo.version}. The version is immutable.`)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function downloadMemo(format: 'markdown' | 'html' | 'json') {
    if (!memoSaved) {
      setError('Save the memo before exporting it.')
      return
    }
    setBusy(`memo-export-${format}`)
    setError(null)
    try {
      const blob = await api.researchMemoDownload(String(memoSaved.object_id), format)
      const suffix = format === 'markdown' ? 'md' : format
      saveBlob(blob, `research-memo-${String(memoSaved.object_id)}.${suffix}`)
      setMessage(
        `${format} export downloaded. Its manifest carries the content hash and the evidence dependencies.`,
      )
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function checkMemo() {
    if (!memoSaved) {
      setError('Save the memo before checking for evidence changes.')
      return
    }
    setBusy('memo-check')
    setError(null)
    try {
      const changeReport = await api.researchMemoCheck(String(memoSaved.object_id))
      setMemoChange(changeReport)
      setMessage(
        `${changeReport.status}: ${(changeReport.categories ?? []).join(', ')} · ` +
          `${(changeReport.findings ?? []).length} finding(s) · the saved memo is unchanged`,
      )
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function download() {
    if (!selected) return
    setBusy('package')
    setError(null)
    try {
      const assumptions: Row = {}
      if (roe.trim()) assumptions.sustainable_roe = Number(roe) / 100
      if (coe.trim()) assumptions.cost_of_equity = Number(coe) / 100
      const built = await api.equityPackage(selected, {
        assumptions,
        as_of: cutoff || undefined,
        method: report?.valuation?.method ?? undefined,
      })
      const binary = atob(String(built.package_base64 ?? ''))
      const bytes = new Uint8Array(binary.length)
      for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
      saveBlob(new Blob([bytes], { type: 'application/zip' }), 'equity-research.atlas')
      setMessage('Research package downloaded. It is declarative and unsigned; the hash proves integrity only.')
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function saveResearch() {
    if (!selected || !report?.metadata) {
      setError('Generate a report before saving a research application.')
      return
    }
    setBusy('save')
    setError(null)
    try {
      const institution = report.valuation?.institution ?? {}
      const assumptionInputs: Row = {
        sustainable_roe: roe.trim() ? Number(roe) / 100 : null,
        cost_of_equity: coe.trim() ? Number(coe) / 100 : null,
      }
      const evidenceIds = (workspace?.provenance?.evidence_details ?? [])
        .map((item: Row) => item.evidence_id)
        .filter((item: unknown): item is string => typeof item === 'string' && item.length > 0)
      const sourceIds = new Set<string>(report.metadata.source_ids ?? ['sec-edgar'])
      if ((regulatory?.subsidiaries?.length ?? 0) > 0) sourceIds.add('fdic-bankfind')
      if (regulatory?.holding_company?.status === 'available') sourceIds.add('ffiec-nic-bhcf')
      const market = report.valuation?.market
      const stamp = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
      const document: Row = {
        schema_version: 'atlas.research_object.v1',
        kind: 'application',
        name: `Bank research · ${workspace?.company?.ticker ?? selected} · ${stamp}`,
        version: '1.0.0',
        status: 'validated',
        description: `Reproducible consolidated bank research for ${workspace?.company?.legal_name ?? selected}.`,
        as_of: report.metadata.as_of,
        mode: report.metadata.mode,
        evidence_ids: [...new Set(evidenceIds)],
        source_ids: [...sourceIds],
        assumptions: Object.fromEntries(
          Object.entries(assumptionInputs).filter(([, value]) => value != null),
        ),
        limitations: [
          ...(workspace?.limitations ?? []),
          ...(institution.limitations ?? []),
        ],
        spec: {
          purpose: 'Reopen and deterministically reproduce this bank research report without executable code.',
          views: [
            { id: 'report', type: 'report', title: 'Equity research report' },
            { id: 'regulatory', type: 'evidence', title: 'Consolidated and subsidiary regulatory evidence' },
            { id: 'model', type: 'table', title: 'Bank residual-income model and assumptions' },
          ],
          application: {
            type: 'equity_research',
            identifier: selected,
            ticker: workspace?.company?.ticker ?? null,
            cik: workspace?.company?.cik ?? null,
            company: workspace?.company?.legal_name ?? null,
          },
          method: report.valuation?.method ?? null,
          information_cutoff: report.metadata.as_of,
          assumption_inputs: assumptionInputs,
          resolved_assumptions: institution.assumptions ?? {},
          result: {
            report_sha256: report.metadata.report_sha256,
            value_per_share: institution.outputs?.value_per_share ?? null,
            calculated_equity_value: institution.outputs?.calculated_equity_value ?? null,
            economically_supported: Boolean(report.metadata.valuation_economically_supported),
          },
          regulatory_evidence: {
            status: regulatory?.status ?? null,
            parent: regulatory?.holding_company?.status === 'available' ? {
              legal_name: regulatory.holding_company.parent?.legal_name ?? null,
              rssd: regulatory.holding_company.parent?.rssd ?? null,
              form: 'FR Y-9C',
              period_end: regulatory.holding_company.latest?.period_end ?? null,
              publication: regulatory.holding_company.latest?.publication ?? null,
              point_in_time_claim: regulatory.holding_company.point_in_time_claim ?? null,
            } : null,
            subsidiaries: (regulatory?.subsidiaries ?? []).map((block: Row) => ({
              entity_id: block.entity?.entity_id ?? null,
              legal_name: block.entity?.legal_name ?? null,
              cert: block.entity?.cert ?? null,
              basis: block.entity?.consolidation_basis ?? null,
              period_end: block.latest?.period_end ?? null,
            })),
          },
          market_context: market ? {
            status: market.status ?? null,
            price_date: market.price_date ?? null,
            source_id: market.source_id ?? null,
            export_allowed: Boolean(market.export_allowed),
            price_included: false,
            observation_pin: market.pin ?? null,
            observation_id: market.observation_id ?? market.source_selection?.observation_id ?? null,
            pin_status: market.pin_status ?? null,
            exact_replay: market.exact_replay ?? null,
          } : null,
        },
      }
      const created = await api.createResearchObject(document)
      setMessage(`Saved research application ${created.object_id}. Reopen it to reproduce the report.`)
      setSavedRevision((value) => value + 1)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function reopenResearch(objectId: string) {
    setBusy(`reopen:${objectId}`)
    setError(null)
    try {
      const object = await api.researchObject(objectId)
      const document = object.document as Row
      const spec = document.spec ?? {}
      const application = spec.application ?? {}
      if (application.type !== 'equity_research' || !application.identifier) {
        throw new Error('This application is not a bank research application.')
      }
      const restoredCutoff = String(spec.information_cutoff ?? document.as_of ?? '').slice(0, 10)
      const inputs = spec.assumption_inputs ?? {}
      const restoredRoe = inputs.sustainable_roe == null ? '' : String(Number(inputs.sustainable_roe) * 100)
      const restoredCoe = inputs.cost_of_equity == null ? '' : String(Number(inputs.cost_of_equity) * 100)
      setSelected(application.identifier)
      setCutoff(restoredCutoff)
      setRoe(restoredRoe)
      setCoe(restoredCoe)
      const assumptions: Row = {}
      if (inputs.sustainable_roe != null) assumptions.sustainable_roe = Number(inputs.sustainable_roe)
      if (inputs.cost_of_equity != null) assumptions.cost_of_equity = Number(inputs.cost_of_equity)
      const built = await api.equityReport(application.identifier, {
        assumptions,
        as_of: restoredCutoff || undefined,
        method: spec.method ?? undefined,
      })
      setReport(built)
      const expected = spec.result?.report_sha256
      if (expected && expected !== built.metadata?.report_sha256) {
        setError(`Reopened application did not reproduce the saved report hash (${expected} vs ${built.metadata?.report_sha256}).`)
      } else {
        setMessage(`Reopened ${objectId} · report ${String(built.metadata?.report_sha256 ?? '').slice(0, 16)}… reproduced.`)
      }
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (error && !coverage) return <ErrorState error={new Error(error)} />
  if (!coverage) return <Loading label="Loading SEC coverage" />
  if (!(coverage.items ?? []).length) return <EmptyState title="No issuers stored" detail="Run the Phase 9 database builder." />

  const metrics = workspace?.metrics?.metrics ?? {}
  const quality: Row[] = workspace?.quality_checks ?? []
  const audit = report?.valuation?.audit
  const valuation = report?.valuation
  const findings: Row[] = valuation?.findings ?? []
  const checks: Row[] = audit?.checks ?? []

  return (
    <div className="page equity-page">
      <SectionHeader
        eyebrow="Phase 9 · integrated equity research"
        title="Source-grounded equity research"
        detail="Every number is an SEC fact with an evidence id. Coverage, model eligibility, execution and the independent DCF audit are reported as separate facts."
        actions={
          <div className="equity-actions">
            <button className="button" onClick={generate} disabled={busy !== null || !selected}>
              {busy === 'report' ? 'Building report…' : 'Generate report'}
            </button>
            <button className="button secondary" onClick={download} disabled={busy !== null || !selected || (row?.valuation_eligibility?.status !== 'eligible' && !row?.valuation_eligibility?.financial_institution)}>
              {busy === 'package' ? 'Packaging…' : 'Download package'}
            </button>
          </div>
        }
      />

      <div className="equity-summary">
        <div><span className="eyebrow">Issuers</span><strong>{coverage.issuers}</strong></div>
        <div><span className="eyebrow">Valid financial coverage</span><strong>{coverage.financial_coverage_valid}</strong></div>
        <div><span className="eyebrow">Valuation eligible</span><strong>{coverage.valuation_eligible}</strong></div>
        <div><span className="eyebrow">DCF executes</span><strong>{coverage.dcf_executes ?? coverage.valuation_executes}</strong></div>
        <div><span className="eyebrow">Institution models</span><strong>{coverage.institution_models_execute ?? 0}</strong></div>
        <div><span className="eyebrow">Economically supported</span><strong>{coverage.valuation_economically_supported}</strong></div>
        <div><span className="eyebrow">Methodology rejected</span><strong>{coverage.methodology_rejected}</strong></div>
        <div><span className="eyebrow">Market prices</span><strong>{coverage.with_prices}</strong></div>
      </div>

      <p className="muted small">
        {coverage.coverage_note} A company can have valid reported statements and still be ineligible for an
        unlevered FCFF DCF, and an executing model is not an economically validated valuation.
      </p>

      {message && <div className="banner banner-ok small">{message}</div>}
      {error && <div className="banner banner-warn small">{error}</div>}

      <div className="equity-layout">
        <div className="equity-list card">
          <div className="equity-list-head">
            <span>Issuer</span>
            <span>Coverage</span>
            <span>Valuation</span>
            <span>Value / share</span>
          </div>
          {(coverage.items ?? []).map((item: Row) => {
            const readiness = (coverage.readiness?.items ?? []).find(
              (entry: Row) => entry.issuer_id === item.issuer_id,
            )
            return (
              <button
                key={item.issuer_id}
                className={`equity-row ${selected === item.issuer_id ? 'is-selected' : ''}`}
                onClick={() => setSelected(item.issuer_id)}
              >
                <span>
                  <strong>{item.ticker ?? item.legal_name}</strong>
                  <span className="muted small"> · {item.legal_name}</span>
                </span>
                <span>
                  <Badge tone={item.financial_coverage_valid ? 'positive' : 'warn'}>
                    {item.financial_coverage_valid ? 'valid' : 'incomplete'}
                  </Badge>
                </span>
                <span>
                  <Badge tone={eligibilityTone(item.valuation_eligibility?.status ?? 'unknown')}>
                    {item.valuation_eligibility?.financial_institution
                      ? item.valuation_eligibility?.method ?? 'institution'
                      : item.valuation_eligibility?.status ?? 'unknown'}
                  </Badge>
                </span>
                <span className="mono">
                  {readiness?.valuation_executes && readiness?.value_per_share != null
                    ? `${money(readiness.value_per_share)}`
                    : '—'}
                </span>
              </button>
            )
          })}
        </div>

        <div className="equity-detail">
          {!row || !workspace ? (
            <Loading label="Loading issuer workspace" />
          ) : (
            <>
              <div className="card">
                <h3>{workspace.company?.legal_name}</h3>
                <div className="muted small">
                  Method {row.valuation_method ?? '—'} · contract{' '}
                  {row.valuation_eligibility?.contract_state ?? 'not evaluated'} · business model{' '}
                  {row.business_model ?? '—'}
                </div>
                <div className="muted small">
                  Ticker {row.ticker ?? 'not mapped'} · CIK {row.cik} · SIC {row.sic ?? '—'} · fiscal year end{' '}
                  {row.fiscal_year_end ?? '—'} · cutoff {workspace.as_of} ({workspace.mode})
                </div>
                {row.ticker_identity?.candidates?.length > 1 && (
                  <p className="muted small">
                    SEC lists {row.ticker_identity.candidates.length} instruments for this registrant without
                    mapping share classes. Atlas uses the declared primary ticker; the identity remains{' '}
                    {row.ticker_identity.status}.
                  </p>
                )}
                <div className="equity-metrics">
                  {[
                    ['Revenue', money(metrics.revenue?.value)],
                    ['Operating margin', pct(metrics.operating_margin?.value)],
                    ['Free cash flow', money(metrics.free_cash_flow?.value)],
                    ['Total debt', money(metrics.total_debt?.value)],
                    ['Cash', money(metrics.cash_and_equivalents?.value)],
                    ['Shares', num(metrics.weighted_average_shares_diluted?.value, 0)],
                  ].map(([label, value]) => (
                    <div key={label as string}>
                      <span className="eyebrow">{label}</span>
                      <strong className="mono">{value}</strong>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card">
                <h3>Valuation eligibility</h3>
                <p className="small">
                  <Badge tone={eligibilityTone(row.valuation_eligibility?.status ?? 'unknown')}>
                    {row.valuation_eligibility?.status}
                  </Badge>{' '}
                  <span className="mono">{row.valuation_eligibility?.method}</span>
                </p>
                <ul className="small muted">
                  {(row.valuation_eligibility?.reasons ?? []).map((reason: string) => (
                    <li key={reason}>{reason}</li>
                  ))}
                  {row.financial_coverage_missing?.length > 0 && (
                    <li>Missing reported concepts: {row.financial_coverage_missing.join(', ')}.</li>
                  )}
                </ul>
              </div>

              <div className="card">
                <h3>Research controls</h3>
                <div className="equity-metrics">
                  <div>
                    <span className="eyebrow">Information cutoff</span>
                    <input data-testid="equity-cutoff" className="mono" type="date" value={cutoff} onChange={(event) => setCutoff(event.target.value)} />
                  </div>
                  <div>
                    <span className="eyebrow">Sustainable ROE (%)</span>
                    <input data-testid="equity-roe" className="mono" inputMode="decimal" placeholder="reported" value={roe} onChange={(event) => setRoe(event.target.value)} />
                  </div>
                  <div>
                    <span className="eyebrow">Cost of equity (%)</span>
                    <input data-testid="equity-coe" className="mono" inputMode="decimal" placeholder="model default" value={coe} onChange={(event) => setCoe(event.target.value)} />
                  </div>
                </div>
                <div className="equity-actions">
                  <button className="button secondary" onClick={applyCutoff} disabled={busy !== null}>Apply cutoff</button>
                  <button className="button" onClick={generate} disabled={busy !== null}>Recalculate</button>
                  <button className="button secondary" onClick={rejectDcf} disabled={busy !== null}>Test FCFF DCF</button>
                </div>
              </div>

              {regulatory?.holding_company?.status === 'available' && (
                <div className="card" data-testid="equity-regulatory-parent">
                  <h3>Consolidated holding company · FR Y-9C</h3>
                  <p className="small">
                    {regulatory.holding_company.parent?.legal_name} · top-tier RSSD{' '}
                    <span className="mono">{regulatory.holding_company.parent?.rssd}</span> · period{' '}
                    <span className="mono">{regulatory.holding_company.latest?.period_end}</span>{' '}
                    <Badge tone="positive">consolidated</Badge>
                  </p>
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>FR Y-9C field</th><th>Value</th><th>Schedule</th><th>Definition</th></tr></thead>
                      <tbody>
                        {['total_assets', 'total_equity_capital', 'goodwill', 'allowance_for_credit_losses', 'net_income', 'cash_dividends_common', 'net_interest_income', 'risk_weighted_assets', 'regulatory_total_capital', 'common_equity_tier_1_ratio', 'tier_1_risk_based_ratio', 'tier_1_leverage_ratio'].map((field) => {
                          const item = regulatory.holding_company.latest?.values?.[field]
                          if (!item) return null
                          const shown = item.value === null
                            ? 'missing'
                            : item.unit === 'USD_thousands'
                              ? money(Number(item.value) * 1000)
                              : `${num(item.value)}%`
                          return (
                            <tr key={field}>
                              <td className="mono">{item.field_code}</td>
                              <td className="mono">{shown}</td>
                              <td className="small">{item.schedule}</td>
                              <td className="small">{item.definition}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className="muted small">
                    Publication timestamp: {regulatory.holding_company.latest?.publication?.published_at || 'not present in the bulk archive'}.
                    {' '}The archive is refreshed in place, so this is a consolidated snapshot, not a point-in-time
                    regulatory reconstruction. It is not added to the FDIC subsidiary and does not set current
                    minimum capital requirements.
                  </p>
                </div>
              )}

              {regulatory && (regulatory.subsidiaries?.length ?? 0) > 0 && (
                <div className="card">
                  <h3>Regulatory evidence · {regulatory.status}</h3>
                  {regulatory.subsidiaries.map((block: Row) => (
                    <div key={block.entity?.entity_id}>
                      <p className="small">
                        {block.entity?.legal_name} · FDIC certificate {block.entity?.cert} ·{' '}
                        <Badge tone={block.status === 'available' ? 'positive' : 'warn'}>{block.status}</Badge>{' '}
                        {block.latest?.period_end && <span className="mono">{block.latest.period_end}</span>}
                      </p>
                      {block.latest && (
                        <div className="table-wrap">
                          <table>
                            <thead><tr><th>Field</th><th>Value</th><th>Definition</th></tr></thead>
                            <tbody>
                              {['ASSET', 'EQ', 'INTAN', 'NIMY', 'NTLNLSR', 'RBC1AAJ', 'RBCRWAJ', 'IDT1CER'].map((field) => {
                                const item = block.latest.values?.[field]
                                if (!item) return null
                                const shown = item.unit === 'USD_thousands' ? money(Number(item.value) * 1000) : `${num(item.value)}%`
                                return <tr key={field}><td className="mono">{field}</td><td className="mono">{shown}</td><td className="small">{item.definition}</td></tr>
                              })}
                            </tbody>
                          </table>
                        </div>
                      )}
                      <p className="muted small">
                        Subsidiary standalone report. It is not added to consolidated parent equity and is not divided by parent shares.
                      </p>
                    </div>
                  ))}
                </div>
              )}                  <div className="card" data-testid="equity-market-context">
                    <h3>Market price and model comparison</h3>
                    {(() => {
                      const securityId =
                        report?.valuation?.market?.pin?.security_id ??
                        report?.valuation?.market?.source_selection?.observation?.security_id
                      if (!securityId) return null
                      return (
                        <ObservationProvenance
                          securityId={String(securityId)}
                          issuerId={report?.company?.issuer?.issuer_id ?? selected}
                          asOf={cutoff || undefined}
                          replay={(pin) =>
                            api.equityReport(selected ?? '', {
                              as_of: cutoff || undefined,
                              observation_pin: pin,
                            })
                          }
                        />
                      )
                    })()}
                    {report?.valuation?.market?.status === 'available' ? (
                      <>
                        <p className="small">
                          Price <strong className="mono">{money(report.valuation.market.price)}</strong> on{' '}
                      <span className="mono">{report.valuation.market.price_date}</span> · source{' '}
                      <span className="mono">{report.valuation.market.source_id}</span> · adjustment{' '}
                      <span className="mono">{report.valuation.market.adjustment_semantics ?? 'not stated'}</span> · mixed date:{' '}
                      <Badge tone={report.valuation.market.mixed_date ? 'warn' : 'positive'}>
                        {report.valuation.market.mixed_date ? 'yes' : 'no'}
                      </Badge>{' '}
                      · export allowed: <strong>{report.valuation.market.export_allowed ? 'yes' : 'no'}</strong>
                    </p>
                    <p className="small muted">{report.valuation.market.warning}</p>
                    {report.valuation.market.implied?.status === 'available' && (
                      <p className="small">Market-implied cost of equity <strong>{pct(report.valuation.market.implied.implied_cost_of_equity)}</strong></p>
                    )}
                  </>
                ) : (
                  <p className="muted small">No observed price matches this issuer. Atlas does not synthesise one.</p>
                )}
                <label className="eyebrow" htmlFor="price-csv">Import permitted daily closes (date,open,high,low,close,volume)</label>
                <textarea
                  id="price-csv"
                  className="mono"
                  rows={3}
                  style={{ width: '100%' }}
                  value={priceCsv}
                  onChange={(event) => setPriceCsv(event.target.value)}
                  placeholder="2026-11-05,320.10,324.00,318.50,322.22,9000000"
                />
                <button className="button secondary" onClick={importPrices} disabled={busy !== null || !priceCsv.trim()}>
                  {busy === 'prices' ? 'Importing…' : 'Import restricted prices'}
                </button>
              </div>

              <div className="card">
                <h3>Reconciliation and quality checks</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Check</th>
                        <th>Expected</th>
                        <th>Actual</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {quality.map((check) => (
                        <tr key={check.name}>
                          <td>{check.name}</td>
                          <td className="mono">{check.expected}</td>
                          <td className="mono">{check.actual}</td>
                          <td>
                            <Badge tone={check.status === 'pass' || check.status === 'reconciled' ? 'positive' : check.status === 'fail' ? 'negative' : 'neutral'}>
                              {check.status}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {audit && (
                <div className="card">
                  <h3>Independent DCF component audit</h3>
                  <p className="small">
                    Verdict <Badge tone={audit.economically_supported ? 'positive' : 'warn'}>{audit.verdict}</Badge>{' '}
                    · terminal value share {pct(audit.terminal_value_share, 1)} · share basis{' '}
                    <span className="mono">{audit.share_denominator?.basis}</span>
                  </p>
                  <p className="muted small">{audit.share_denominator?.limitation}</p>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Component</th>
                          <th>Formula</th>
                          <th>Recomputed</th>
                          <th>Engine</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {checks.map((check) => (
                          <tr key={check.name}>
                            <td>{check.name}</td>
                            <td className="mono small">{check.formula}</td>
                            <td className="mono">
                              {Array.isArray(check.expected) ? `${check.expected.length} periods` : money(check.expected)}
                            </td>
                            <td className="mono">
                              {Array.isArray(check.actual) ? `${check.actual.length} periods` : money(check.actual)}
                            </td>
                            <td>
                              <Badge tone={check.status === 'pass' ? 'positive' : 'negative'}>{check.status}</Badge>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {findings.length > 0 && (
                    <>
                      <h4>Findings</h4>
                      <ul className="small">
                        {findings.map((finding) => (
                          <li key={finding.code}>
                            <span className="mono">{finding.code}</span> · {finding.severity} · {finding.message}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              )}

              {report?.report && (
                <div className="card">
                  <h3>Source-linked research report</h3>
                  <pre className="equity-report">{report.report}</pre>
                </div>
              )}

              {report?.valuation?.institution?.driver && (
                <div className="card">
                  <h3>Bank model v2 · regulatory context</h3>
                  <p className="small">
                    Driver <span className="mono">{report.valuation.institution.driver.label}</span> · tangible book{' '}
                    <Badge tone={report.valuation.institution.tangible_book?.status === 'available_subsidiary_only' ? 'warn' : 'neutral'}>
                      {report.valuation.institution.tangible_book?.status}
                    </Badge>
                  </p>
                  <p className="small" data-testid="equity-value-per-share">
                    Value per share <strong className="mono" data-testid="equity-value-number">
                      {money(report.valuation.institution.outputs?.value_per_share)}
                    </strong>{' '}
                    USD · method <span className="mono">{report.valuation.method}</span> · economically supported{' '}
                    <strong>{report.valuation.economically_supported ? 'yes' : 'no'}</strong>.
                  </p>
                  <p className="muted small">{report.valuation.institution.tangible_book?.detail}</p>
                  {report.valuation.institution.capital?.status === 'available' && (
                    <p className="small">
                      CET1 {num(report.valuation.institution.capital.observed_percent.common_equity_tier_1)}% · leverage{' '}
                      {num(report.valuation.institution.capital.observed_percent.tier_1_leverage)}% · binding headroom{' '}
                      {num(report.valuation.institution.capital.binding_headroom_points)} pp
                    </p>
                  )}
                  <p className="muted small">Subsidiary capital evidence. Headroom is in percentage points; dollar RWA is not published.</p>
                </div>
              )}

              <div className="card" data-testid="equity-saved-panel">
                <h3>Saved bank research</h3>
                <p className="muted small">
                  A saved application records the company, information cutoff, selected method, assumption inputs,
                  source and regulatory identities, report hash and limitations. It never records the restricted
                  market price. Reopening rebuilds the report through the same deterministic engine.
                </p>
                <button
                  className="button secondary"
                  data-testid="equity-save"
                  onClick={saveResearch}
                  disabled={busy !== null || !report}
                >
                  {busy === 'save' ? 'Saving…' : 'Save research application'}
                </button>
                {saved.length > 0 ? (
                  <div className="equity-saved-list">
                    {saved.map((item) => (
                      <div className="equity-saved-item" key={item.object_id}>
                        <span className="small">
                          <strong className="mono">{item.object_id}</strong> · {item.name}
                        </span>
                        <button
                          className="button secondary small"
                          onClick={() => reopenResearch(item.object_id)}
                          disabled={busy !== null}
                        >
                          {busy === `reopen:${item.object_id}` ? 'Reopening…' : 'Reopen'}
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted small">No saved application exists for this company yet.</p>
                )}
              </div>

              <div className="card" data-testid="equity-memo-panel">
                <h3>Evidence-grounded research memo</h3>
                <p className="muted small">
                  Every factual and numeric statement in the memo is a claim that resolves to stored evidence or a
                  reproducible transformation. Analyst assumptions and hypotheses stay separate from reported facts,
                  and nothing is recalculated again for the export.
                </p>
                <div className="equity-actions">
                  <button
                    className="button secondary"
                    data-testid="equity-memo-create"
                    onClick={createMemo}
                    disabled={busy !== null || !selected}
                  >
                    {busy === 'memo' ? 'Building…' : 'Create research memo'}
                  </button>
                  <button
                    className="button secondary"
                    data-testid="equity-memo-save"
                    onClick={saveMemo}
                    disabled={busy !== null || !memo}
                  >
                    {busy === 'memo-save' ? 'Saving…' : 'Save memo version'}
                  </button>
                  <button
                    className="button secondary"
                    data-testid="equity-memo-check"
                    onClick={checkMemo}
                    disabled={busy !== null || !memoSaved}
                  >
                    {busy === 'memo-check' ? 'Checking…' : 'Check for new evidence'}
                  </button>
                </div>
                {memo ? (
                  <div className="small" data-testid="equity-memo-summary">
                    <p>
                      <strong className="mono">{String(memo.memo_id ?? '')}</strong> · hash{' '}
                      <span className="mono">{String(memo.content_hash ?? '').slice(0, 16)}…</span> ·{' '}
                      {(memo.claims ?? []).length} claims · {memo.issuer?.valuation_method}
                    </p>
                    <ul className="equity-integrity-list">
                      {Object.entries(memo.integrity?.dimensions ?? {}).map(([name, payload]) => (
                        <li key={name} data-testid={`equity-memo-integrity-${name}`}>
                          <strong>{name}</strong>: {(payload as Row).outcome} — {(payload as Row).detail}
                        </li>
                      ))}
                    </ul>
                    {memo.integrity?.failures?.length > 0 && (
                      <p className="muted small">
                        Failures are reported, not hidden: the memo keeps the failing claims and their diagnostics.
                      </p>
                    )}
                    {!memo.rights?.redistributable && (
                      <p className="small">
                        Export is refused: {(memo.rights?.blocked_sources ?? []).map((item: Row) => item.source_id).join(', ')}{' '}
                        does not permit redistribution.
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="muted small">No memo has been built for this issuer in this session.</p>
                )}
                {memoSaved ? (
                  <div className="equity-actions">
                    {(['markdown', 'html', 'json'] as const).map((format) => (
                      <button
                        key={format}
                        className="button secondary small"
                        data-testid={`equity-memo-export-${format}`}
                        onClick={() => downloadMemo(format)}
                        disabled={busy !== null}
                      >
                        {busy === `memo-export-${format}` ? 'Exporting…' : `Download ${format}`}
                      </button>
                    ))}
                  </div>
                ) : null}
                {memoChange ? (
                  <div className="small" data-testid="equity-memo-change">
                    <p>
                      <strong>{memoChange.status}</strong> · {(memoChange.categories ?? []).join(', ') || 'no findings'}
                    </p>
                    {(memoChange.findings ?? []).slice(0, 6).map((finding: Row, index: number) => (
                      <p key={`${finding.category}-${index}`} className="muted small">
                        <strong>{finding.category}</strong>: {finding.detail}
                      </p>
                    ))}
                  </div>
                ) : null}
              </div>

              {valuation && valuation.status !== 'supported' && (
                <div className="card">
                  <h3>Valuation declined</h3>
                  <p className="small">
                    {valuation.status}: {valuation.reason}
                  </p>
                  <p className="muted small">
                    Atlas does not substitute a comparable-company multiple, a synthetic price or an invented
                    revenue base.
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
