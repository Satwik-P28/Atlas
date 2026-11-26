import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, api, type CompanyComparison } from '../api'
import { Badge, EmptyState, ErrorState, Loading, SectionHeader } from '../components/ui'
import { useAsync } from '../state'

/** Cross-company comparison of verified figures.
 *
 * The page exists to answer one question honestly: are these numbers comparable? It never
 * normalises a currency, a scale or a consolidation scope to make a tidier table, and it
 * shows the incompatibility instead of the ratio. */
export default function Compare() {
  const companies = useAsync(() => api.companies(), [])
  const concepts = useAsync(() => api.answerConcepts(), [])

  const [selected, setSelected] = useState<string[]>([])
  const [pickedConcepts, setPickedConcepts] = useState<string[]>(['revenue'])
  const [period, setPeriod] = useState('')
  const [cutoff, setCutoff] = useState('')
  const [result, setResult] = useState<CompanyComparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (selected.length || !companies.data?.items?.length) return
    setSelected(companies.data.items.slice(0, 2).map((item) => item.issuer_id))
  }, [companies.data, selected.length])

  const canRun = selected.length >= 2 && pickedConcepts.length > 0 && period.trim().length > 0

  const toggle = useCallback((value: string, list: string[], set: (next: string[]) => void, max: number) => {
    if (list.includes(value)) {
      set(list.filter((item) => item !== value))
      return
    }
    if (list.length >= max) return
    set([...list, value])
  }, [])

  async function run() {
    if (!canRun) return
    setBusy(true)
    setError(null)
    try {
      setResult(
        await api.compareCompanies({
          issuers: selected,
          concepts: pickedConcepts,
          period: period.trim(),
          as_of: cutoff || null,
        }),
      )
    } catch (caught) {
      setResult(null)
      setError(
        caught instanceof ApiError
          ? `${caught.message}${caught.code ? ` (${caught.code})` : ''}`
          : caught instanceof Error
            ? caught.message
            : 'Comparison failed',
      )
    } finally {
      setBusy(false)
    }
  }

  const companyName = useMemo(() => {
    const map = new Map<string, string>()
    for (const item of companies.data?.items ?? []) map.set(item.issuer_id, item.legal_name)
    return map
  }, [companies.data])

  return (
    <div className="page">
      <SectionHeader
        eyebrow="Comparison workspace"
        title="Compare only what is comparable"
        detail="Each company's figure is resolved by the same concept resolver over the same period, and every cell keeps its accession, table coordinates and availability. A currency, scale, consolidation-scope or coverage difference is reported as a finding; a blocking finding means Atlas will not present the comparison as valid."
        actions={result && <Badge tone={result.comparable ? 'positive' : 'warn'}>
          {result.comparable ? 'comparable' : 'incompatible inputs'}
        </Badge>}
      />
      {companies.loading && <Loading label="Loading companies" />}
      {companies.error && <ErrorState error={companies.error} onRetry={companies.reload} />}
      {concepts.error && <ErrorState error={concepts.error} onRetry={concepts.reload} />}

      <div className="card">
        <div className="inline-form">
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
            <input className="field" type="date" value={cutoff} onChange={(event) => setCutoff(event.target.value)} />
          </label>
          <button className="button" onClick={() => void run()} disabled={!canRun || busy} data-testid="compare-run">
            {busy ? 'Comparing…' : 'Compare'}
          </button>
        </div>
        <p className="muted small">
          Two to six companies, one to eight concepts. An information cutoff restricts every cited
          filing to what was public at that instant; leave it empty to use the present.
        </p>
      </div>

      <div className="card">
        <h3>Companies</h3>
        <div className="toolbar wrap">
          {(companies.data?.items ?? []).map((item) => (
            <button
              key={item.issuer_id}
              className={`chip${selected.includes(item.issuer_id) ? ' is-on' : ''}`}
              onClick={() => toggle(item.issuer_id, selected, setSelected, 6)}
              data-testid={`compare-company-${item.issuer_id}`}
            >
              {item.legal_name}
            </button>
          ))}
        </div>
        {selected.length < 2 && <p className="muted small">Select at least two companies.</p>}
      </div>

      <div className="card">
        <h3>Concepts</h3>
        <div className="toolbar wrap">
          {(concepts.data?.items ?? []).map((item) => (
            <button
              key={item.key}
              className={`chip${pickedConcepts.includes(item.key) ? ' is-on' : ''}`}
              title={item.statement}
              onClick={() => toggle(item.key, pickedConcepts, setPickedConcepts, 8)}
              data-testid={`compare-concept-${item.key}`}
            >
              {item.aliases[0] ?? item.key}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="card" role="alert">
          <p className="error-text">{error}</p>
        </div>
      )}

      {!result && !error && !busy && (
        <EmptyState
          title="No comparison yet"
          detail="Pick companies, concepts and a period, then compare. Atlas will show each company's verified cell or refuse it with the reason."
        />
      )}

      {result && (
        <>
          <div className="card">
            <p className="muted small">
              Period {result.period} · cutoff {result.cutoff} · scope {result.scope}. {result.note}
            </p>
          </div>
          {result.concepts.map((block) => (
            <div className="card" key={block.concept} data-testid={`compare-block-${block.concept}`}>
              <div className="section-header">
                <div>
                  <h3>{block.concept.replace(/_/g, ' ')}</h3>
                  <p className="muted small">{block.statement}</p>
                </div>
                <Badge tone={block.comparable ? 'positive' : 'warn'}>
                  {block.comparable ? 'comparable' : 'not comparable'}
                </Badge>
              </div>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Company</th>
                      <th>Status</th>
                      <th>Value</th>
                      <th>Currency</th>
                      <th>Scale</th>
                      <th>Scope</th>
                      <th>Evidence</th>
                      <th>Availability</th>
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row) => (
                      <tr key={row.requested}>
                        <td>{row.legal_name ?? row.requested}</td>
                        <td>
                          <Badge tone={row.status === 'resolved' ? 'positive' : 'warn'}>{row.status}</Badge>
                          {row.reason && <div className="muted small">{row.reason}</div>}
                        </td>
                        <td className="numeric">{row.value ?? '—'}</td>
                        <td>{row.currency ?? '—'}</td>
                        <td>{row.scale === null ? '—' : `10^${row.scale}`}</td>
                        <td>{row.entity_scope ?? '—'}</td>
                        <td className="small">
                          {row.evidence ? (
                            <>
                              <div>{row.evidence.accession}</div>
                              <div className="muted">{row.evidence.row_label}</div>
                              <div className="muted mono small">{row.evidence.cell_id}</div>
                            </>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td className="small">
                          {row.availability ? (
                            <>
                              <div>{row.availability.availability_precision ?? 'unknown'}</div>
                              <div className="muted">{row.availability.availability_time}</div>
                              {row.availability.is_estimated && <Badge tone="warn">modelled bound</Badge>}
                            </>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {block.findings.length > 0 && (
                <div className="stack" style={{ gap: 6, marginTop: 10 }}>
                  {block.findings.map((finding) => (
                    <div key={`${finding.code}-${finding.message}`} className="small">
                      <Badge tone={finding.severity === 'blocking' ? 'negative' : 'neutral'}>
                        {finding.severity === 'blocking' ? 'blocking' : 'disclosed'}
                      </Badge>{' '}
                      <code>{finding.code}</code> <span className="muted">{finding.message}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </>
      )}
      <p className="muted small">
        Companies are limited to those stored in this Atlas database
        {companyName.size ? ` (${companyName.size} available)` : ''}. A comparison of stored
        figures is not an industry index, a peer-set average or a valuation opinion.
      </p>
    </div>
  )
}
