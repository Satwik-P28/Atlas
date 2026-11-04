import { useEffect, useState } from 'react'
import { api } from '../api'
import MetricGrid from '../components/MetricGrid'
import StatementTable from '../components/StatementTable'
import XrayPanel from '../components/XrayPanel'
import { Badge, EmptyState, ErrorState, Loading, SectionHeader } from '../components/ui'
import { fmtDate } from '../format'
import { useAsync } from '../state'
import type { AsOfMode } from '../types'

export default function Research() {
  const companies = useAsync(() => api.companies(), [])
  const [issuer, setIssuer] = useState('')
  const [date, setDate] = useState('2024-06-01')
  const [mode, setMode] = useState<AsOfMode>('public_available')
  const [statement, setStatement] = useState<'income' | 'balance' | 'cashflow'>('income')
  const [period, setPeriod] = useState<'FY' | 'Q'>('FY')
  const [evidenceId, setEvidenceId] = useState<string | null>(null)

  useEffect(() => {
    if (!issuer && companies.data?.items.length) setIssuer(companies.data.items[0].issuer_id)
  }, [companies.data, issuer])

  const asOf = `${date}T23:59:59Z`
  const statements = useAsync(
    () => (issuer ? api.statements(issuer, { statement, period, asOf, mode, limit: 8 }) : Promise.resolve(null)),
    [issuer, statement, period, asOf, mode],
  )
  const metrics = useAsync(
    () => (issuer ? api.metrics(issuer, { asOf, mode }) : Promise.resolve(null)),
    [issuer, asOf, mode],
  )

  return (
    <div className="page">
      <SectionHeader
        eyebrow="Research"
        title="Time machine"
        detail="Reconstruct what Atlas can support as publicly available on a chosen date, using the same selection policy the CLI uses."
        actions={<Badge tone="accent">policy atlas.select.point_in_time.v2</Badge>}
      />

      <section className="card">
        <div className="toolbar wrap">
          <label className="inline-field">
            Company
            <select className="field" value={issuer} onChange={(event) => setIssuer(event.target.value)}>
              {companies.data?.items.map((company) => (
                <option key={company.issuer_id} value={company.issuer_id}>
                  {company.legal_name}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            Information date
            <input className="field mono" type="date" value={date} onChange={(event) => setDate(event.target.value)} />
          </label>
          <label className="inline-field">
            Semantics
            <select className="field" value={mode} onChange={(event) => setMode(event.target.value as AsOfMode)}>
              <option value="public_available">Publicly available</option>
              <option value="atlas_ingested">Atlas-ingested</option>
            </select>
          </label>
          <label className="inline-field">
            Statement
            <select className="field" value={statement} onChange={(event) => setStatement(event.target.value as typeof statement)}>
              <option value="income">Income</option>
              <option value="balance">Balance sheet</option>
              <option value="cashflow">Cash flow</option>
            </select>
          </label>
          <label className="inline-field">
            Period
            <select className="field" value={period} onChange={(event) => setPeriod(event.target.value as typeof period)}>
              <option value="FY">Annual</option>
              <option value="Q">Quarterly</option>
            </select>
          </label>
        </div>
        <div className="banner banner-info">
          <div>
            <strong>What this date means.</strong> A historical market price alone does not prove today's database can
            reconstruct every fact known then. {mode === 'public_available'
              ? 'Atlas shows only facts whose public availability timestamp is on or before this instant.'
              : 'Atlas shows only facts it had ingested by this instant — which may be later than public availability.'}
          </div>
        </div>
      </section>

      {statements.loading && <Loading label="Reconstructing" />}
      {statements.error && <ErrorState error={statements.error} onRetry={statements.reload} />}
      {statements.data && (
        <div className="stack">
          <div className="asof-summary">
            <div>
              <div className="eyebrow">Reconstruction at {fmtDate(asOf)}</div>
              <h3>{statements.data.issuer.legal_name}</h3>
              <div className="muted small">
                {statements.data.completeness} · {statements.data.excluded_not_yet_available} not yet available ·{" "}
                {statements.data.excluded_unknown_availability} unknown availability · {statements.data.contradictions.length} contradiction(s)
              </div>
            </div>
            <Badge tone={statements.data.completeness === 'complete_for_query' ? 'positive' : 'warn'}>
              {statements.data.completeness === 'complete_for_query' ? 'provably complete for this query' : statements.data.completeness}
            </Badge>
          </div>

          <section className="card">
            <SectionHeader eyebrow="Financial statements" title="As reported, as knowable" detail="Click a value to inspect its original filing, availability and revision chain." />
            <StatementTable
              data={statements.data}
              onSelect={(cell) => cell.evidence_id && setEvidenceId(cell.evidence_id)}
              selectedEvidence={evidenceId}
            />
          </section>

          {metrics.data && (
            <section className="card">
              <SectionHeader eyebrow="Metrics" title="Ratios on this information set" detail="Values use only the facts available at the chosen date; the price date is stated per metric." />
              <MetricGrid data={metrics.data} onEvidence={setEvidenceId} />
            </section>
          )}
        </div>
      )}
      {!statements.data && !statements.loading && <EmptyState title="Choose a company and date" />}

      {evidenceId && <XrayPanel evidenceId={evidenceId} onClose={() => setEvidenceId(null)} />}
    </div>
  )
}
