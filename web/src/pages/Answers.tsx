import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ApiError,
  api,
  type AnswerCertificateResponse,
  type AnswerResolution,
} from '../api'
import { Badge, ErrorState, Loading, SectionHeader } from '../components/ui'
import { fmtDate } from '../format'
import { useAsync } from '../state'

interface Refusal {
  code: string
  message: string
  reason?: string | null
  candidates?: Array<Record<string, unknown>>
}

/** Answer certificates: one question, one verified cell, one checkable artefact.
 *
 * The page never hides the difference between "the arithmetic matches the cells" and
 * "the cells are the right economic concept". That distinction is the product. */

/** The unit arrives as an object ({kind, scale}); printing it directly shows [object Object]. */
function formatAnswerValue(answer: { value?: unknown; unit?: unknown }): string {
  const raw = answer.value === null || answer.value === undefined ? '—' : String(answer.value)
  const unit = answer.unit as { kind?: string; scale?: number } | string | undefined
  if (unit === undefined || unit === null) return raw
  if (typeof unit === 'string') return `${raw} ${unit}`.trim()
  const scale = typeof unit.scale === 'number' ? ` (10^${unit.scale})` : ''
  return `${raw} ${unit.kind ?? ''}${scale}`.trim()
}

export default function Answers() {
  const [params] = useSearchParams()
  const companies = useAsync(() => api.companies(), [])
  const concepts = useAsync(() => api.answerConcepts(), [])

  const [issuer, setIssuer] = useState(params.get('issuer') ?? '')
  const [concept, setConcept] = useState(params.get('concept') ?? 'revenue')
  const [period, setPeriod] = useState(params.get('period') ?? '')
  const [cutoff, setCutoff] = useState('')
  const [question, setQuestion] = useState('')
  const [resolution, setResolution] = useState<AnswerResolution | null>(null)
  const [certificate, setCertificate] = useState<AnswerCertificateResponse | null>(null)
  const [verification, setVerification] = useState<Record<string, any> | null>(null)
  const [refusal, setRefusal] = useState<Refusal | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'resolve' | 'certificate' | 'verify' | null>(null)

  useEffect(() => {
    if (!issuer && companies.data?.items?.length) setIssuer(companies.data.items[0].issuer_id)
  }, [companies.data, issuer])

  useEffect(() => {
    const fromUrl = params.get('concept')
    if (fromUrl) setConcept(fromUrl)
  }, [params])

  const conceptRecord = useMemo(
    () => concepts.data?.items.find((item) => item.key === concept),
    [concepts.data, concept],
  )

  const request = useCallback(
    () => ({
      issuer_id: issuer,
      concept,
      period: period.trim(),
      as_of: cutoff || null,
      scope: 'consolidated' as const,
    }),
    [issuer, concept, period, cutoff],
  )

  function describe(err: unknown): Refusal {
    if (err instanceof ApiError) {
      const context = (err.context ?? {}) as Record<string, any>
      return {
        code: err.code,
        message: err.message,
        reason: context.reason ?? null,
        candidates: Array.isArray(context.candidates) ? context.candidates : [],
      }
    }
    return { code: 'request_failed', message: err instanceof Error ? err.message : 'Request failed' }
  }

  async function resolve() {
    if (!issuer || !concept || !period.trim()) return
    setBusy('resolve')
    setError(null)
    setRefusal(null)
    setCertificate(null)
    setVerification(null)
    try {
      setResolution(await api.resolveAnswer(request()))
    } catch (err) {
      setResolution(null)
      setRefusal(describe(err))
    } finally {
      setBusy(null)
    }
  }

  async function build() {
    if (!issuer || !concept || !period.trim()) return
    setBusy('certificate')
    setError(null)
    setRefusal(null)
    setVerification(null)
    try {
      const payload = await api.answerCertificate({
        ...request(),
        research_question: question.trim() || undefined,
      })
      // The certificate response is not an AnswerResolution: it carries no `question`, and
      // storing it as one blanked the answer block on the next render (it read
      // `resolution.question.issuer_id`). Keep the resolution that produced the certificate.
      setCertificate(payload)
    } catch (err) {
      setCertificate(null)
      setRefusal(describe(err))
    } finally {
      setBusy(null)
    }
  }

  async function verify() {
    if (!certificate) return
    setBusy('verify')
    setError(null)
    try {
      const payload = await api.verifyCertificate(certificate.certificate)
      setVerification(payload.report)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification failed')
    } finally {
      setBusy(null)
    }
  }

  function download() {
    if (!certificate) return
    const blob = new Blob([JSON.stringify(certificate.certificate, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `atlas-certificate-${certificate.evidence.cell_id}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  const answer = resolution?.answer
  const evidence = resolution?.evidence
  const limitations = [
    ...((answer?.limitations as string[] | undefined) ?? []),
    ...((certificate?.certificate.limitations as string[] | undefined) ?? []),
  ]

  return (
    <div className="page">
      <SectionHeader
        eyebrow="Answer certificates"
        title="One question, one verified cell, one checkable artefact"
        detail="Atlas resolves a financial concept to exactly one verified consolidated cell, performs typed arithmetic and packages the result with its accession, table coordinates, units and availability. When the concept is not unique it refuses and lists what it considered."
        actions={conceptRecord && <Badge tone="accent">{conceptRecord.statement}</Badge>}
      />
      {companies.loading && <Loading label="Loading companies" />}
      {companies.error && <ErrorState error={companies.error} onRetry={companies.reload} />}
      {concepts.error && <ErrorState error={concepts.error} onRetry={concepts.reload} />}

      <div className="card">
        <div className="inline-form">
          <label className="inline-field">
            Company
            <select className="field" value={issuer} onChange={(event) => setIssuer(event.target.value)}>
              {(companies.data?.items ?? []).map((item) => (
                <option key={item.issuer_id} value={item.issuer_id}>
                  {item.legal_name}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            Concept
            <select className="field" value={concept} onChange={(event) => setConcept(event.target.value)}>
              {(concepts.data?.items ?? []).map((item) => (
                <option key={item.key} value={item.key}>
                  {item.aliases[0] ?? item.key}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            Period
            <input
              className="field"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
              placeholder="e.g. 2023"
              inputMode="numeric"
            />
          </label>
          <label className="inline-field">
            Information cutoff
            <input
              className="field"
              type="date"
              value={cutoff}
              onChange={(event) => setCutoff(event.target.value)}
            />
          </label>
          <label className="inline-field">
            Research question
            <input
              className="field"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="optional; recorded on the certificate"
            />
          </label>
        </div>
        <div className="toolbar">
          <button className="button button-primary" onClick={resolve} disabled={busy !== null || !period.trim()}>
            {busy === 'resolve' ? 'Resolving…' : 'Resolve answer'}
          </button>
          <button className="button" onClick={build} disabled={busy !== null || !period.trim()}>
            {busy === 'certificate' ? 'Building…' : 'Build certificate'}
          </button>
          <button className="button" onClick={verify} disabled={!certificate || busy !== null}>
            {busy === 'verify' ? 'Verifying…' : 'Verify independently'}
          </button>
          <button className="button" onClick={download} disabled={!certificate}>
            Download certificate JSON
          </button>
        </div>
        {conceptRecord && (
          <p className="small muted">
            Definition: {conceptRecord.aliases.join(' · ')} — {conceptRecord.statement}{' '}
            {conceptRecord.kind}. {conceptRecord.segment_sensitive ? 'Segment-sensitive: consolidated scope only.' : 'Not segment-sensitive.'}
          </p>
        )}
      </div>

      {error && <div className="banner banner-warn">{error}</div>}

      {refusal && (
        <div className="card" role="alert">
          <SectionHeader
            eyebrow="Refused"
            title={refusal.reason ? refusal.reason.replace(/_/g, ' ') : 'No unique verified cell'}
          />
          <p className="muted">
            Atlas did not approximate. {refusal.message}
          </p>
          {refusal.code === 'answer_refused' && refusal.candidates && refusal.candidates.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Period</th>
                  <th>Scope</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {refusal.candidates.map((candidate, index) => (
                  <tr key={`${String(candidate.accession)}-${index}`}>
                    <td>
                      {String(candidate.row_label ?? '—')}{' '}
                      <span className="small muted">{String(candidate.accession ?? '')}</span>
                    </td>
                    <td>{String(candidate.period ?? '—')}</td>
                    <td>{String(candidate.entity_scope ?? '—')}</td>
                    <td className="mono">{String(candidate.score ?? '—')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="small muted">
            Supported concepts: {(concepts.data?.items ?? []).map((item) => item.key).join(', ')}
          </p>
        </div>
      )}

      {answer && evidence && resolution && (
        <div className="card">
          <SectionHeader
            eyebrow="Answer"
            title={formatAnswerValue(answer)}
            detail={answer.formula ?? undefined}
            actions={
              <Badge tone={resolution.availability.is_estimated ? 'warn' : 'positive'}>
                {resolution.availability.is_estimated ? 'availability estimated' : 'availability observed'}
              </Badge>
            }
          />
          <div className="split-2">
            <dl className="kv">
              <dt>Issuer</dt>
              <dd>{resolution.question.issuer_id}</dd>
              <dt>Consolidation scope</dt>
              <dd>{String(evidence.entity_scope ?? 'unknown')}</dd>
              <dt>Statement</dt>
              <dd>{String(evidence.statement_title ?? evidence.statement_family ?? '—')}</dd>
              <dt>Accession</dt>
              <dd className="mono">{evidence.accession}</dd>
              <dt>Table / unit</dt>
              <dd className="mono">
                {evidence.table_id} / {evidence.unit_id}
              </dd>
              <dt>Cell</dt>
              <dd className="mono">{evidence.cell_id}</dd>
            </dl>
            <dl className="kv">
              <dt>Row</dt>
              <dd>
                {evidence.row_label} <span className="mono small">({evidence.row})</span>
              </dd>
              <dt>Column</dt>
              <dd>
                {evidence.column_label} <span className="mono small">({evidence.column})</span>
              </dd>
              <dt>Period</dt>
              <dd>{evidence.period ?? '—'}</dd>
              <dt>Currency / scale</dt>
              <dd>
                {evidence.currency ?? 'unknown'} / {evidence.scale === null ? 'unknown' : `10^${evidence.scale}`}
              </dd>
              <dt>Raw text</dt>
              <dd className="mono">“{evidence.raw}”</dd>
              <dt>Rights</dt>
              <dd>{evidence.rights ?? '—'}</dd>
            </dl>
          </div>
          <div className="notice">
            <strong>Availability.</strong> {resolution.availability.note}{' '}
            {resolution.availability.availability_time
              ? `Recorded instant: ${fmtDate(resolution.availability.availability_time)} (${resolution.availability.availability_precision ?? 'unknown'}).`
              : 'No availability instant is recorded.'}
          </div>
          <div className="notice notice-warn">
            <strong>Verified, not proven correct.</strong> {resolution.semantics.note}
          </div>
          {answer.verification && (
            <p className="small muted mono">
              Verification: {JSON.stringify(answer.verification)}
            </p>
          )}
          <p className="small muted">
            Resolver {resolution.resolver.version}. {resolution.resolver.xbrl_status}.
          </p>
        </div>
      )}

      {certificate && (
        <div className="card">
          <SectionHeader
            eyebrow="Certificate"
            title={`atlas.research_certificate.v1 · ${String(certificate.certificate.certificate_version)}`}
            detail={`Fingerprint ${String(certificate.certificate.certificate_fingerprint)}`}
            actions={
              <Badge tone="neutral" title="A fingerprint proves internal consistency, not authority">
                fingerprint, not a signature
              </Badge>
            }
          />
          <table className="data-table">
            <thead>
              <tr>
                <th>Binding</th>
                <th>Period</th>
                <th>Currency</th>
                <th>Scale</th>
                <th>Availability</th>
              </tr>
            </thead>
            <tbody>
              {(certificate.certificate.input_bindings as Array<Record<string, any>>).map((binding) => (
                <tr key={String(binding.cell_id)}>
                  <td>
                    {String(binding.row_label)} · {String(binding.column_label)}
                    <span className="mono small"> {String(binding.cell_id)}</span>
                  </td>
                  <td>{String(binding.period ?? '—')}</td>
                  <td>{String(binding.currency ?? 'unknown')}</td>
                  <td>{binding.scale === null ? 'unknown' : `10^${String(binding.scale)}`}</td>
                  <td>
                    {String(binding.availability_precision ?? 'unknown')}
                    {binding.availability_is_estimated ? ' · estimated bound' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {verification && (
            <div className="stack">
              <SectionHeader
                eyebrow="Independent verification"
                title={`${String(verification.level)} · ${String(verification.status)}`}
                detail={verification.recomputed_value ? `Recomputed ${String(verification.recomputed_value)}` : undefined}
              />
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Check</th>
                    <th>Passed</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {(verification.checks as Array<Record<string, any>>).map((check, index) => (
                    <tr key={`${String(check.check)}-${index}`}>
                      <td className="mono">{String(check.check)}</td>
                      <td>
                        {check.passed ? <Badge tone="positive">pass</Badge> : <Badge tone="negative">fail</Badge>}
                      </td>
                      <td className="small muted">{check.detail ? String(check.detail) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(verification.reasons as string[]).length > 0 && (
                <p className="small muted">Reasons: {(verification.reasons as string[]).join('; ')}</p>
              )}
            </div>
          )}
          <details className="small muted">
            <summary>Certificate JSON</summary>
            <pre className="mono small">{JSON.stringify(certificate.certificate, null, 2)}</pre>
          </details>
        </div>
      )}

      {limitations.length > 0 && (
        <div className="card">
          <SectionHeader eyebrow="Limitations" title="What this answer does not establish" />
          <ul className="small muted">
            {[...new Set(limitations)].map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
