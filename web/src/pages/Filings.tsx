import { useEffect, useState } from 'react'
import { api, type KnowledgeClaim, type KnowledgeSearch, type KnowledgeUnit } from '../api'
import { Badge, ErrorState, Loading, SectionHeader } from '../components/ui'
import { fmtDate } from '../format'
import { useAsync } from '../state'

/** Standard-mode document research: ask a question, read the passages that were
 * publicly available at the cutoff, open the exact span, and check a claim. */
export default function Filings() {
  const companies = useAsync(() => api.companies(), [])
  const [issuer, setIssuer] = useState('')
  const [query, setQuery] = useState('customer concentration risk')
  const [cutoff, setCutoff] = useState('')
  const [search, setSearch] = useState<KnowledgeSearch | null>(null)
  const [unit, setUnit] = useState<KnowledgeUnit | null>(null)
  const [claim, setClaim] = useState<KnowledgeClaim | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!issuer && companies.data?.items?.length) setIssuer(companies.data.items[0].issuer_id)
  }, [companies.data, issuer])

  async function run() {
    if (!issuer) return
    setBusy(true)
    setError(null)
    setClaim(null)
    setUnit(null)
    try {
      setSearch(
        await api.knowledgeSearch({
          query,
          issuer_id: issuer,
          cutoff: cutoff ? `${cutoff}T23:59:59Z` : undefined,
          limit: 8,
        }),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Retrieval failed')
    } finally {
      setBusy(false)
    }
  }

  async function inspect(unitId: string) {
    try {
      setUnit(await api.knowledgeUnit(unitId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Passage could not be opened')
    }
  }

  async function verify() {
    if (!issuer) return
    try {
      setClaim(
        await api.knowledgeClaim({
          issuer_id: issuer,
          cutoff: cutoff ? `${cutoff}T23:59:59Z` : new Date().toISOString(),
          key: query.slice(0, 60).toLowerCase().replace(/[^a-z0-9]+/g, '-'),
          question: query,
        }),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Claim could not be verified')
    }
  }

  const selected = companies.data?.items.find((item) => item.issuer_id === issuer)

  return (
    <div className="page">
      <SectionHeader
        eyebrow="Filings"
        title="Document research"
        detail="Search the primary documents Atlas has archived for this company. Results are limited to what was publicly available at your cutoff, each passage keeps its exact character span, and a question with no supporting passage returns an abstention rather than a guess."
        actions={search && <Badge tone="accent">{search.plan.retriever}</Badge>}
      />
      {companies.loading && <Loading label="Loading companies" />}
      {companies.error && <ErrorState error={companies.error} onRetry={companies.reload} />}
      <div className="card filing-controls">
        <label>
          <span className="eyebrow">Company</span>
          <select value={issuer} onChange={(event) => setIssuer(event.target.value)}>
            {(companies.data?.items ?? []).map((item) => (
              <option key={item.issuer_id} value={item.issuer_id}>
                {item.legal_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="eyebrow">Question</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. customer concentration risk" />
        </label>
        <label>
          <span className="eyebrow">Information cutoff</span>
          <input type="date" value={cutoff} onChange={(event) => setCutoff(event.target.value)} />
        </label>
        <div className="filing-actions">
          <button className="button" onClick={run} disabled={busy || !issuer}>
            {busy ? 'Retrieving…' : 'Search filings'}
          </button>
          <button className="button secondary" onClick={verify} disabled={!issuer || !search?.results.length}>
            Verify as a claim
          </button>
        </div>
      </div>
      {error && <div className="banner banner-warn">{error}</div>}

      {search && (
        <div className="card">
          <div className="filing-meta">
            <span>
              <strong>{search.count}</strong> passages · {search.plan.policy} ·{' '}
              {search.plan.cutoff ? `cutoff ${fmtDate(search.plan.cutoff)}` : 'latest available'} ·{' '}
              {search.latency_ms.toFixed(1)} ms
            </span>
            {search.excluded.later_than_cutoff > 0 && (
              <Badge tone="warn">{search.excluded.later_than_cutoff} later passages excluded</Badge>
            )}
          </div>
          {search.abstained ? (
            <div className="banner banner-warn" role="status">
              No supported passage for this question at this cutoff ({search.abstention_reason?.replace(/_/g, ' ')}).
              Atlas does not answer from an unrelated match.
            </div>
          ) : (
            <ol className="passage-list">
              {search.results.map((row) => (
                <li key={row.unit_id}>
                  <button className="passage" onClick={() => inspect(row.unit_id)} aria-expanded={unit?.unit_id === row.unit_id}>
                    <span className="passage-head">
                      {row.form_type} {row.is_amendment ? '(amended)' : ''} · {row.section_path}
                    </span>
                    <span className="passage-meta mono small">
                      {row.accession} · available {fmtDate(row.availability_time)} ({row.availability_precision}) · chars{' '}
                      {row.char_start}–{row.char_end} · {row.rights}
                    </span>
                    <span className="passage-text">{row.excerpt}</span>
                  </button>
                  {unit?.unit_id === row.unit_id && (
                    <div className="passage-opened">
                      <p>{unit.body}</p>
                      <div className="small muted">
                        Exact span {unit.char_start}–{unit.char_end} in {unit.accession} ·{' '}
                        <a href={unit.resolve_original} target="_blank" rel="noreferrer">
                          open the original filing
                        </a>
                      </div>
                    </div>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {claim && (
        <div className="card">
          <SectionHeader eyebrow="Claim" title={`${claim.epistemic_status.replace(/_/g, ' ')} · ${claim.verification.outcome.replace(/_/g, ' ')}`} detail={claim.statement} />
          <div className="small muted">
            {claim.citations.length} citation(s) · export {claim.verification.export_allowed ? 'permitted' : 'blocked'} ·{' '}
            {claim.verification.diagnostics.map((item) => item.code.replace(/_/g, ' ')).join(', ') || 'no diagnostics'}
          </div>
          {claim.counter_evidence.length > 0 && (
            <div className="small">Counter-evidence candidates: {claim.counter_evidence.map((item) => `${item.section_path} (${item.matched})`).join('; ')}</div>
          )}
          <ul className="small muted">
            {claim.limitations.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {selected && search && (
        <p className="small muted">
          {selected.legal_name} · documents are archived from SEC EDGAR as public records; Atlas stores primary
          documents only and does not redistribute exhibits.
        </p>
      )}
    </div>
  )
}
