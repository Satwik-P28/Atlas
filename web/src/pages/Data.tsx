import { useEffect, useMemo, useState } from 'react'
import { api, type MarketPreview, type OnboardingStatus } from '../api'
import { Badge, ErrorState, Loading, SectionHeader } from '../components/ui'
import { useAsync } from '../state'

const SAMPLE = `date,open,high,low,close,volume
2024-01-02,100.00,102.00,99.00,101.00,1000000
2024-01-03,101.00,103.00,100.00,102.00,1100000
2024-01-04,102.00,104.00,101.00,103.00,1200000
`

function StatusCard({ title, entry }: { title: string; entry: OnboardingStatus['imports'][string] }) {
  return (
    <div className="card">
      <div className="eyebrow">{title}</div>
      <div>
        <Badge tone={entry.available ? 'positive' : 'neutral'}>
          {entry.available ? 'available' : 'not available'}
        </Badge>
      </div>
      {entry.endpoint && <p className="mono small">{entry.endpoint}</p>}
      {entry.command && <p className="mono small">{entry.command}</p>}
      {entry.note && <p className="small muted">{entry.note}</p>}
      {entry.user_agent_configured === false && (
        <p className="small muted">ATLAS_SEC_USER_AGENT is not set; SEC retrieval will refuse.</p>
      )}
    </div>
  )
}

/** Guided onboarding for user-authorised market data.
 *
 * The page previews with the production importer and writes nothing until the user
 * confirms. It records the licence the user declares and never accepts a credential. */
export default function Data() {
  const companies = useAsync(() => api.companies(), [])
  const status = useAsync(() => api.onboardingStatus(), [])

  const securities = useMemo(
    () =>
      (companies.data?.items ?? []).flatMap((item) =>
        (item.securities ?? []).map((security) => ({
          security_id: security.security_id,
          label: `${security.tickers?.[0]?.ticker ?? security.security_id} · ${item.legal_name}`,
        })),
      ),
    [companies.data],
  )

  const [securityId, setSecurityId] = useState('')
  const [mic, setMic] = useState('XNAS')
  const [currency, setCurrency] = useState('USD')
  const [sourceName, setSourceName] = useState('User broker export')
  const [licence, setLicence] = useState('')
  const [csv, setCsv] = useState('')
  const [preview, setPreview] = useState<MarketPreview | null>(null)
  const [busy, setBusy] = useState<'preview' | 'import' | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!securityId && securities.length) setSecurityId(securities[0].security_id)
  }, [securities, securityId])

  const body = () => ({
    security_id: securityId,
    mic,
    csv,
    source_name: sourceName,
    licence,
    currency,
  })

  const ready = Boolean(securityId && mic.trim() && licence.trim().length >= 3 && csv.trim().length > 20)

  async function runPreview() {
    setBusy('preview')
    setError(null)
    try {
      setPreview(await api.previewMarketImport(body()))
    } catch (err) {
      setPreview(null)
      setError(err instanceof Error ? err.message : 'Preview failed')
    } finally {
      setBusy(null)
    }
  }

  async function runImport() {
    if (!preview) return
    setBusy('import')
    setError(null)
    try {
      setPreview(await api.importMarket({ ...body(), confirm: true }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setBusy(null)
    }
  }

  async function readFile(file: File | null) {
    if (!file) return
    setError(null)
    try {
      const text = await file.text()
      setCsv(text)
      setPreview(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The file could not be read as text')
    }
  }

  return (
    <div className="page">
      <SectionHeader
        eyebrow="Data onboarding"
        title="Bring your own authorised market data"
        detail="Atlas bundles no market prices. Import a file you are entitled to use: the importer maps recognised columns, refuses to treat an adjusted series as a raw close, reports every skipped row and stores the licence you declare. Nothing is written until you confirm a preview."
        actions={<Badge tone="neutral">user responsibility</Badge>}
      />
      {status.loading && <Loading label="Checking data capabilities" />}
      {status.error && <ErrorState error={status.error} onRetry={status.reload} />}
      {status.data && (
        <div className="card-grid">
          <StatusCard title="CSV bars" entry={status.data.imports.market_csv} />
          <StatusCard title="Parquet bars" entry={status.data.imports.market_parquet} />
          <StatusCard title="SEC EDGAR filings" entry={status.data.imports.sec_edgar} />
          <StatusCard title="FRED / ALFRED" entry={status.data.imports.fred_alfred} />
        </div>
      )}
      {status.data && (
        <p className="small muted">
          {status.data.database.securities} securities · {status.data.database.bars} stored bars ·{' '}
          credentials accepted here: {status.data.credentials.accepted_by_this_interface.length === 0 ? 'none' : status.data.credentials.accepted_by_this_interface.join(', ')}.{' '}
          {status.data.credentials.policy}
        </p>
      )}

      <div className="card">
        <div className="inline-form">
          <label className="inline-field">
            Security
            <select className="field" value={securityId} onChange={(event) => setSecurityId(event.target.value)}>
              {securities.map((security) => (
                <option key={security.security_id} value={security.security_id}>
                  {security.label}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            Venue (MIC)
            <input className="field" value={mic} onChange={(event) => setMic(event.target.value.toUpperCase())} />
          </label>
          <label className="inline-field">
            Currency
            <input className="field" value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} />
          </label>
          <label className="inline-field">
            Source name
            <input className="field" value={sourceName} onChange={(event) => setSourceName(event.target.value)} />
          </label>
          <label className="inline-field">
            Licence declared by you
            <input
              className="field"
              value={licence}
              onChange={(event) => setLicence(event.target.value)}
              placeholder="e.g. personal research use; no redistribution"
            />
          </label>
        </div>
        <label className="inline-field">
          CSV file
          <input
            className="field"
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => readFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <label className="inline-field">
          …or paste the rows
          <textarea
            className="field"
            rows={8}
            value={csv}
            onChange={(event) => {
              setCsv(event.target.value)
              setPreview(null)
            }}
            placeholder={SAMPLE}
          />
        </label>
        {!securities.length && (
          <p className="banner banner-warn">
            No securities are registered in this database, so there is nothing to attach bars to.
            Synchronise an issuer first (<span className="mono">atlas sec sync</span>) or run{' '}
            <span className="mono">atlas demo</span>.
          </p>
        )}
        <div className="toolbar">
          <button className="button button-primary" onClick={runPreview} disabled={!ready || busy !== null}>
            {busy === 'preview' ? 'Previewing…' : 'Preview import'}
          </button>
          <button className="button" onClick={runImport} disabled={!preview || preview.wrote_anything || busy !== null}>
            {busy === 'import' ? 'Importing…' : 'Confirm and import'}
          </button>
          <button
            className="button"
            onClick={() => {
              setCsv(SAMPLE)
              setPreview(null)
            }}
          >
            Use the sample rows
          </button>
        </div>
        {!licence.trim() && (
          <p className="small muted">
            A licence declaration is required: Atlas records where the data came from and on what
            terms, so a later export cannot pretend the data is Atlas-owned.
          </p>
        )}
      </div>

      {error && <div className="banner banner-warn">{error}</div>}

      {preview && (
        <div className="card">
          <SectionHeader
            eyebrow="Preview"
            title={`${preview.bars_accepted} of ${preview.rows_read} rows accepted`}
            detail={`${preview.coverage.first_session ?? '—'} → ${preview.coverage.last_session ?? '—'} · ${preview.coverage.sessions} sessions · ${preview.issue_count} issue(s)`}
            actions={
              <Badge tone={preview.wrote_anything ? 'positive' : 'neutral'}>
                {preview.wrote_anything ? 'imported' : 'nothing written yet'}
              </Badge>
            }
          />
          <div className="split-2">
            <div>
              <div className="eyebrow">Column mapping</div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Atlas field</th>
                    <th>File column</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(preview.columns).map(([field, column]) => (
                    <tr key={field}>
                      <td>{field}</td>
                      <td className={column ? 'mono' : 'muted'}>{column ?? 'not found'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small muted">File columns: {preview.source_columns.join(', ')}</p>
              {preview.adjusted_columns_ignored.length > 0 && (
                <p className="banner banner-warn">
                  Ignored derived column(s): {preview.adjusted_columns_ignored.join(', ')}. Atlas stores raw
                  closes and derives adjusted series from corporate actions.
                </p>
              )}
            </div>
            <div>
              <div className="eyebrow">Duplicates and history</div>
              <p className="small muted">{preview.duplicates.policy}</p>
              <dl className="kv">
                <dt>Bars already stored</dt>
                <dd className="mono">{preview.duplicates.bars_already_stored_for_series}</dd>
                <dt>Repeated in file</dt>
                <dd className="mono">{preview.duplicates.sessions_repeated_in_file.length || 0}</dd>
                <dt>Rows skipped</dt>
                <dd className="mono">{preview.rows_skipped}</dd>
              </dl>
              {preview.issues.length > 0 && (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Issue</th>
                      <th>Severity</th>
                      <th>Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.issues.map((issue, index) => (
                      <tr key={`${issue.code}-${index}`}>
                        <td className="mono">{issue.code}</td>
                        <td>{issue.severity ?? 'error'}</td>
                        <td className="small muted">{issue.detail ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
          <div className="notice">
            <strong>Rights.</strong> {preview.rights.note} Declared licence: “{preview.rights.licence}”.
          </div>
          {preview.wrote_anything && (
            <div className="notice">
              <strong>Stored.</strong> {preview.summary ?? `${preview.stored?.inserted ?? 0} inserted`} · source{' '}
              <span className="mono">{preview.source_id}</span>. Large imports are not atomic across the whole
              file: re-running the import is safe because a bar for the same session becomes a revision rather
              than a second observation.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
