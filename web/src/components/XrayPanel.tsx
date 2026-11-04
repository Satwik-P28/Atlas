import { api } from '../api'
import { useAsync } from '../state'
import { fmtDate, fmtDateTime, fmtUnit } from '../format'
import { Badge, ErrorState, Loading } from './ui'

export default function XrayPanel({
  evidenceId,
  onClose,
  inline = false,
}: {
  evidenceId: string | null
  onClose?: () => void
  inline?: boolean
}) {
  const { data, error, loading } = useAsync(
    () => (evidenceId ? api.xray(evidenceId) : Promise.resolve(null)),
    [evidenceId],
  )

  if (!evidenceId) return null
  if (loading) return <aside className={inline ? 'xray-inline' : 'xray-panel'}><Loading label="Loading provenance" /></aside>
  if (error || !data)
    return (
      <aside className={inline ? 'xray-inline' : 'xray-panel'}>
        <ErrorState error={error ?? new Error('No provenance returned')} />
        {onClose && <button className="button" onClick={onClose}>Close</button>}
      </aside>
    )

  const record = data.record
  const chain = data.revision_chain ?? []
  return (
    <aside className={inline ? 'xray-inline' : 'xray-panel'} aria-label="Financial X-Ray">
      <div className="xray-head">
        <div>
          <div className="eyebrow">Financial X-Ray</div>
          <h3>{record.concept?.replace(/_/g, ' ') ?? 'Evidence record'}</h3>
          <div className="xray-value mono">{fmtUnit(record.value ?? null, record.unit)}</div>
        </div>
        {onClose && (
          <button className="icon-button" aria-label="Close X-Ray" onClick={onClose}>
            ✕
          </button>
        )}
      </div>

      <dl className="kv">
        <dt>Evidence</dt>
        <dd className="mono">{String(record.evidence_id ?? evidenceId)}</dd>
        <dt>Period</dt>
        <dd>
          {fmtDate(record.period_start)} → {fmtDate(record.period_end)}
        </dd>
        <dt>Reported value</dt>
        <dd className="mono">
          {record.value} {record.unit}
        </dd>
        <dt>Availability</dt>
        <dd>
          {fmtDateTime(record.availability_time)} <Badge tone="neutral">{String(record.availability_precision ?? '')}</Badge>
        </dd>
        <dt>Atlas ingested</dt>
        <dd>{fmtDateTime(record.observed_at)}</dd>
        <dt>Quality</dt>
        <dd>
          {String(record.quality)} · {String(record.verification)}
        </dd>
        <dt>Source concept</dt>
        <dd className="mono small">{String(record.source_concept ?? '—')}</dd>
        <dt>Derivation</dt>
        <dd>
          {String(record.derivation_kind).replace(/_/g, ' ')}
          {record.derivation_rule ? ` · ${record.derivation_rule}` : ''}
        </dd>
      </dl>

      <section>
        <h4>Source document</h4>
        <p className="small muted">
          {String(data.source?.name ?? data.source?.source_id ?? 'unknown source')}
          {data.source?.licence ? ` · ${String(data.source.licence)}` : ''}
        </p>
        <p className="mono small break">{String(data.raw_document?.url ?? '—')}</p>
        <p className="muted small">
          hash {String(data.raw_document?.content_hash ?? '').slice(0, 16)}… retrieved{" "}
          {fmtDateTime(String(data.raw_document?.retrieved_at ?? ''))}
        </p>
      </section>

      {data.filing && (
        <section>
          <h4>Filing</h4>
          <p className="small">
            {String((data.filing as Record<string, unknown>).form_type ?? '')} ·{" "}
            {String((data.filing as Record<string, unknown>).accession_number ?? '')} · filed{" "}
            {fmtDate(String((data.filing as Record<string, unknown>).filed_date ?? ''))}
          </p>
        </section>
      )}

      <section>
        <h4>How this number was produced</h4>
        <ol className="narrative">
          {(data.narrative ?? []).map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
      </section>

      {chain.length > 1 && (
        <section>
          <h4>Revision chain</h4>
          <table className="mini-table">
            <thead>
              <tr>
                <th>Evidence</th>
                <th>Kind</th>
                <th>Available</th>
                <th className="numeric">Value</th>
              </tr>
            </thead>
            <tbody>
              {chain.map((entry, index) => (
                <tr key={index} className={entry.evidence_id === record.evidence_id ? 'is-current' : ''}>
                  <td className="mono small">{String(entry.evidence_id ?? '').slice(0, 14)}…</td>
                  <td className="small">{String(entry.revision_kind ?? '')}</td>
                  <td className="small">{fmtDateTime(String(entry.availability_time ?? ''))}</td>
                  <td className="numeric mono small">{String(entry.value ?? '—')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {data.derived_inputs?.length > 0 && (
        <section>
          <h4>Derived inputs</h4>
          <ul className="plain small mono">
            {data.derived_inputs.map((input, index) => (
              <li key={index}>{JSON.stringify(input)}</li>
            ))}
          </ul>
        </section>
      )}

      {data.limitations?.length > 0 && (
        <section>
          <h4>Limitations</h4>
          <ul className="plain small">
            {data.limitations.map((limitation, index) => (
              <li key={index}>{limitation}</li>
            ))}
          </ul>
        </section>
      )}

      <p className="muted small">
        {data.terminal?.holds} · policy {data.terminal?.policy}
      </p>
    </aside>
  )
}
