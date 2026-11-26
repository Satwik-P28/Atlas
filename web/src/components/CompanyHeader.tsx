import { useState } from 'react'
import type { CompanyDetail } from '../types'
import { Badge } from './ui'

export default function CompanyHeader({ company }: { company: CompanyDetail }) {
  const [showWarnings, setShowWarnings] = useState(false)
  const primary = company.securities[0]
  const tickers = company.securities.flatMap((security) =>
    security.tickers.map((ticker) => ({ ...ticker, classDesignation: security.class_designation })),
  )
  return (
    <header className="company-header">
      <div className="company-title">
        <div>
          <div className="eyebrow">
            {company.entity_type ?? 'issuer'} · CIK {company.cik ?? '—'}
            {company.fiscal_year_end ? ` · FYE ${company.fiscal_year_end}` : ''}
          </div>
          <h1>{company.legal_name}</h1>
          <div className="ticker-row">
            {tickers.length > 0 ? (
              tickers.map((ticker, index) => (
                <span key={`${ticker.ticker}-${index}`} className="ticker-chip mono">
                  {ticker.ticker ?? '—'}
                  <span className="muted small"> {ticker.mic ?? ''}</span>
                  {ticker.status && ticker.status !== 'confirmed' && (
                    <Badge tone="warn" title={`Ticker assignment status: ${ticker.status}`}>
                      {ticker.status}
                    </Badge>
                  )}
                </span>
              ))
            ) : (
              <span className="muted">No evidenced ticker</span>
            )}
          </div>
        </div>
        <div className="company-stats">
          <div>
            <span className="stat-value mono">{company.evidence_count.toLocaleString()}</span>
            <span className="stat-label">evidence records</span>
          </div>
          <div>
            <span className="stat-value mono">{company.filing_count.toLocaleString()}</span>
            <span className="stat-label">SEC filings</span>
          </div>
          <div>
            <span className="stat-value mono">{company.availability.exact.toLocaleString()}</span>
            <span className="stat-label">exact availability</span>
          </div>
          {primary?.last_bar_date && (
            <div>
              <span className="stat-value mono">{primary.last_bar_date}</span>
              <span className="stat-label">last market session</span>
            </div>
          )}
        </div>
      </div>
      <div className="company-flags">
        {company.availability.date > 0 && (
          <Badge tone="warn" title="Date-only availability: an intraday answer may be wrong">
            {company.availability.date} date-precision
          </Badge>
        )}
        {company.availability.unknown > 0 && <Badge tone="negative">{company.availability.unknown} unknown availability</Badge>}
        {tickers.some((ticker) => ticker.status !== 'confirmed') && (
          <Badge tone="neutral" title="SEC does not evidence listing dates; ticker start is the observation date">
            ticker history unevidenced
          </Badge>
        )}
        <button className="link-button small" onClick={() => setShowWarnings((value) => !value)}>
          {showWarnings ? 'hide data notes' : `data notes (${company.warnings.length})`}
        </button>
      </div>
      {showWarnings && (
        <ul className="company-warnings small muted">
          {company.warnings.map((warning, index) => (
            <li key={index}>{warning}</li>
          ))}
          <li>Identity is never merged by ticker; share classes remain separate securities.</li>
        </ul>
      )}
    </header>
  )
}
