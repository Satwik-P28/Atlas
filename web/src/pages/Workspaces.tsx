import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAsync, useSettings } from '../state'
import { fmtDate } from '../format'
import { Badge, EmptyState, ErrorState, Loading, SectionHeader } from '../components/ui'
import type { WorkspaceDocument } from '../types'

export default function Workspaces() {
  const { mode, setMode } = useSettings()
  const navigate = useNavigate()
  const companies = useAsync(() => api.companies(), [])
  const saved = useAsync(() => api.workspaces(), [])
  const [issuer, setIssuer] = useState('')
  const [security, setSecurity] = useState('')
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)

  const company = useMemo(() => companies.data?.items.find((item) => item.issuer_id === issuer), [companies.data, issuer])
  const presets = useAsync(
    () => (issuer && security ? api.presets(issuer, security) : Promise.resolve(null)),
    [issuer, security],
  )

  useEffect(() => {
    if (!issuer && companies.data?.items.length) {
      const first = companies.data.items.find((item) => item.legal_name.startsWith('Apple')) ?? companies.data.items[0]
      setIssuer(first.issuer_id)
      setSecurity(first.securities[0]?.security_id ?? '')
    }
  }, [companies.data, issuer])

  async function createFromPreset(document: WorkspaceDocument) {
    setBusy(true)
    setError(null)
    try {
      const created = await api.createWorkspace(document)
      navigate(`/workspaces/${created.workspace_id}`)
    } catch (caught) {
      setError(caught as Error)
    } finally {
      setBusy(false)
    }
  }

  if (mode !== 'advanced') {
    return (
      <div className="page">
        <SectionHeader eyebrow="Workspaces" title="Advanced research layouts" detail="Customizable panel workspaces are part of Advanced mode." />
        <section className="card">
          <EmptyState title="Switch to Advanced mode" detail="Standard mode keeps one guided layout per page. Advanced mode unlocks saved panel workspaces." />
          <button className="button button-primary" onClick={() => setMode('advanced')}>
            Enable Advanced mode
          </button>
        </section>
      </div>
    )
  }

  return (
    <div className="page">
      <SectionHeader
        eyebrow="Workspaces"
        title="Saved research layouts"
        detail="A workspace is a validated JSON document: panels, spans and indicator configurations. It cannot execute code, and a generated workspace is reviewed by the same validator as a hand-built one."
        actions={<Badge tone="accent">{saved.data?.items.length ?? 0} saved</Badge>}
      />
      {error && <ErrorState error={error} />}

      <section className="card">
        <SectionHeader eyebrow="New workspace" title="Start from a preset" detail="Presets are built in the same schema and validated server-side." />
        <div className="toolbar wrap">
          <label className="inline-field">
            Company
            <select
              className="field"
              value={issuer}
              onChange={(event) => {
                setIssuer(event.target.value)
                const next = companies.data?.items.find((item) => item.issuer_id === event.target.value)
                setSecurity(next?.securities[0]?.security_id ?? '')
              }}
            >
              {companies.data?.items.map((item) => (
                <option key={item.issuer_id} value={item.issuer_id}>
                  {item.legal_name}
                </option>
              ))}
            </select>
          </label>
          {(company?.securities.length ?? 0) > 1 && (
            <label className="inline-field">
              Share class
              <select className="field" value={security} onChange={(event) => setSecurity(event.target.value)}>
                {company?.securities.map((item) => (
                  <option key={item.security_id} value={item.security_id}>
                    {item.tickers[0]?.ticker ?? item.class_designation}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {presets.loading && <Loading label="Loading presets" />}
        {presets.data && (
          <div className="preset-grid">
            {presets.data.items.map((preset) => (
              <article className="preset-card" key={preset.name}>
                <div>
                  <div className="eyebrow">{preset.mode} · {preset.columns} columns</div>
                  <h3>{preset.name}</h3>
                  <p className="muted small">{preset.description}</p>
                </div>
                <div className="preset-panels small mono">{preset.panels.map((panel) => panel.type).join(' · ')}</div>
                <button className="button button-primary" disabled={busy} onClick={() => void createFromPreset(preset)}>
                  Create
                </button>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <SectionHeader eyebrow="Saved" title="Your workspaces" detail="Layouts persist in the local database and survive restarts." />
        {saved.loading && <Loading label="Loading workspaces" />}
        {saved.error && <ErrorState error={saved.error} onRetry={saved.reload} />}
        {saved.data && saved.data.items.length === 0 && <p className="muted">Nothing saved yet.</p>}
        {saved.data && saved.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Mode</th>
                  <th className="numeric">Panels</th>
                  <th>Fingerprint</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {saved.data.items.map((workspace) => (
                  <tr key={workspace.workspace_id}>
                    <td>
                      <Link className="text-link" to={`/workspaces/${workspace.workspace_id}`}>
                        {workspace.name}
                      </Link>
                    </td>
                    <td>
                      <Badge tone="neutral">{workspace.mode}</Badge>
                    </td>
                    <td className="numeric mono">{workspace.document.panels.length}</td>
                    <td className="mono small">{workspace.fingerprint}</td>
                    <td className="small">{fmtDate(workspace.updated_at)}</td>
                    <td>
                      <button
                        className="link-button small"
                        onClick={() => {
                          if (!window.confirm(`Delete workspace “${workspace.name}”?`)) return
                          void api.deleteWorkspace(workspace.workspace_id).then(() => saved.reload())
                        }}
                      >
                        delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
