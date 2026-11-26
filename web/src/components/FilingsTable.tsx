import type { FilingsResponse } from '../types'
import { fmtDate, fmtDateTime } from '../format'
import { Badge } from './ui'

export default function FilingsTable({ data }: { data: FilingsResponse }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Form</th>
            <th>Filed</th>
            <th>Period</th>
            <th>Accepted</th>
            <th>Accession</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.items.map((filing) => (
            <tr key={filing.filing_id}>
              <td>
                <span className="form-badge mono">{filing.form_type}</span>{" "}
                {filing.is_amendment && <Badge tone="warn">amended</Badge>}
                <div className="muted small">{filing.form_label}</div>
              </td>
              <td className="mono">{fmtDate(filing.filed_date)}</td>
              <td className="mono">{fmtDate(filing.period_of_report)}</td>
              <td className="small">{fmtDateTime(filing.acceptance_datetime)}</td>
              <td className="mono small">{filing.accession_number}</td>
              <td>
                {filing.source_url ? (
                  <a className="link-button small" href={filing.source_url} target="_blank" rel="noreferrer noopener">
                    EDGAR ↗
                  </a>
                ) : (
                  <span className="muted small">no document</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="table-foot">
        <span className="muted small">
          {data.items.length} of {data.total} filings · SEC filing events only; no licensed news feed
        </span>
      </div>
    </div>
  )
}
