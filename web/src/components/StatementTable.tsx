import type { StatementCell, StatementRow, StatementsResponse } from '../types'
import { fiscalLabel, fmtDate, fmtUnit } from '../format'
import { Badge } from './ui'

export default function StatementTable({
  data,
  onSelect,
  selectedEvidence,
}: {
  data: StatementsResponse
  onSelect: (cell: StatementCell, row: StatementRow) => void
  selectedEvidence?: string | null
}) {
  if (data.columns.length === 0) {
    return (
      <div className="state-block">
        <div>
          <div className="state-title">No {data.period === 'FY' ? 'annual' : 'quarterly'} periods in this view</div>
          <p className="muted">
            Atlas returns nothing rather than a partial period. Try another statement, period, or as-of date.
          </p>
        </div>
      </div>
    )
  }
  return (
    <div className="statement-wrap">
      <table className="statement-table">
        <thead>
          <tr>
            <th className="sticky-col">Line item</th>
            {data.columns.map((column) => (
              <th key={column.period_end} className="numeric">
                <div>{fiscalLabel(column.fiscal_year, column.fiscal_period)}</div>
                <div className="muted small">{fmtDate(column.period_end)}</div>
                {column.revision_kind && column.revision_kind !== 'original' && (
                  <Badge tone="warn" title={`Revision: ${column.revision_kind}`}>
                    {column.revision_kind}
                  </Badge>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.concept}>
              <th scope="row" className="sticky-col">
                <span>{row.label}</span>
                <span className="muted small concept-key">{row.concept}</span>
              </th>
              {row.cells.map((cell, index) => {
                const column = data.columns[index]
                const active = cell.evidence_id && cell.evidence_id === selectedEvidence
                return (
                  <td key={`${row.concept}-${column.period_end}`} className="numeric">
                    {cell.missing ? (
                      <span className="muted" title="Not reported in the source for this period">
                        —
                      </span>
                    ) : (
                      <button
                        className={`cell-button ${active ? 'is-active' : ''}`}
                        onClick={() => onSelect(cell, row)}
                        title={`${cell.evidence_id} · click to open X-Ray`}
                      >
                        {fmtUnit(cell.value, cell.unit)}
                      </button>
                    )}
                    {!cell.missing && cell.revision_count && cell.revision_count > 1 && (
                      <span className="cell-flag" title={`${cell.revision_count} versions in the chain`}>
                        v{cell.revision_count}
                      </span>
                    )}
                    {!cell.missing && cell.availability_precision === 'date' && (
                      <span className="cell-flag" title="Availability evidenced to the day, not an acceptance instant">
                        d
                      </span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="table-foot">
        <span className="muted small">{data.units_note}</span>
        <span className="muted small">
          as-of {fmtDate(data.as_of)} · {data.mode.replace('_', ' ')} · policy {data.policy.split('.').slice(-1)}
        </span>
      </div>
      {(data.excluded_unknown_availability > 0 || data.excluded_not_yet_available > 0 || data.contradictions.length > 0) && (
        <div className="table-notices">
          {data.excluded_not_yet_available > 0 && (
            <div className="notice">
              {data.excluded_not_yet_available} record(s) existed but were not publicly available at this instant.
            </div>
          )}
          {data.excluded_unknown_availability > 0 && (
            <div className="notice notice-warn">
              {data.excluded_unknown_availability} record(s) have unevidenced availability and are excluded; this view is{" "}
              {data.completeness}.
            </div>
          )}
          {data.contradictions.map((contradiction, index) => (
            <div className="notice notice-warn" key={`${contradiction.concept}-${index}`}>
              Contradictory evidence for {contradiction.concept}: {contradiction.values.join(' vs ')}. Selected{" "}
              {contradiction.selected}.
            </div>
          ))}
        </div>
      )}
      <div className="table-foot">
        <span className="muted small">Click any value to open its Financial X-Ray.</span>
        {data.notes.map((note, index) => (
          <span key={index} className="muted small">
            {note}
          </span>
        ))}
      </div>
    </div>
  )
}
