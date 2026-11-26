import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAsync } from '../state'
import { fmtDate } from '../format'
import { Badge, ErrorState, Loading, SectionHeader } from '../components/ui'

export default function Companies() {
  const { data, error, loading, reload } = useAsync(() => api.companies(), [])
  const [filter, setFilter] = useState('')

  const items = useMemo(() => {
    if (!data) return []
    const needle = filter.trim().toLowerCase()
    if (!needle) return data.items
    return data.items.filter((company) => {
      const haystack = [company.legal_name, company.cik ?? '', ...company.securities.flatMap((s) => s.tickers.map((t) => t.ticker ?? ''))]
      return haystack.some((value) => value.toLowerCase().includes(needle))
    })
  }, [data, filter])

  return (
    <div className="page">
      <SectionHeader
        eyebrow="Companies"
        title="Issuers and securities"
        detail="Identity comes from SEC CIK and share-class keys. Tickers are evidence-bearing assignments, not the identity itself."
        actions={
          <input
            className="field"
            placeholder="Filter by name, ticker or CIK"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            aria-label="Filter companies"
          />
        }
      />
      {loading && <Loading label="Loading companies" />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && (
        <div className="company-grid">
          {items.map((company) => (
            <Link key={company.issuer_id} to={`/companies/${company.issuer_id}`} className="company-card">
              <div className="company-card-head">
                <div>
                  <div className="eyebrow">
                    CIK {company.cik ?? '—'} · {company.entity_type ?? 'issuer'}
                  </div>
                  <h3>{company.legal_name}</h3>
                </div>
                <span className="company-card-tickers mono">
                  {company.securities.flatMap((security) => security.tickers.map((ticker) => ticker.ticker)).filter(Boolean).join(' ')}
                </span>
              </div>
              <div className="company-card-stats">
                <div>
                  <span className="mono">{company.evidence_count.toLocaleString()}</span>
                  <span className="muted small">facts</span>
                </div>
                <div>
                  <span className="mono">{company.filing_count.toLocaleString()}</span>
                  <span className="muted small">filings</span>
                </div>
                <div>
                  <span className="mono">{company.securities.length}</span>
                  <span className="muted small">securities</span>
                </div>
                <div>
                  <span className="mono">{company.fiscal_year_end ?? '—'}</span>
                  <span className="muted small">FYE</span>
                </div>
              </div>
              <div className="company-card-foot">
                <span className="muted small">
                  {company.securities[0]?.last_bar_date ? `market to ${fmtDate(company.securities[0].last_bar_date)}` : 'no market data'}
                </span>
                {company.securities.some((security) => security.data_status === 'synthetic') && (
                  <Badge tone="synthetic">synthetic prices</Badge>
                )}
                {company.securities.length > 1 && <Badge tone="neutral">{company.securities.length} share classes</Badge>}
              </div>
            </Link>
          ))}
          {items.length === 0 && <p className="muted">No stored issuer matches “{filter}”.</p>}
        </div>
      )}
    </div>
  )
}
