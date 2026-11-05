import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import '../applications.css'
import { Badge, SectionHeader } from '../components/ui'

type Row = Record<string, any>

const num = (value: unknown, digits = 2) =>
  value == null ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits })

function base64Bytes(encoded: string): Blob {
  const binary = atob(encoded)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return new Blob([bytes], { type: 'application/zip' })
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('The package file could not be read.'))
    reader.onload = () => {
      const result = String(reader.result ?? '')
      resolve(result.includes(',') ? result.slice(result.indexOf(',') + 1) : result)
    }
    reader.readAsDataURL(file)
  })
}

export default function Applications() {
  const [gallery, setGallery] = useState<Row | null>(null)
  const [runs, setRuns] = useState<Row[]>([])
  const [packages, setPackages] = useState<Row[]>([])
  const [selected, setSelected] = useState<Row | null>(null)
  const [execution, setExecution] = useState<Row | null>(null)
  const [runId, setRunId] = useState('')
  const [forkName, setForkName] = useState('')
  const [forkVersion, setForkVersion] = useState('1.0.1')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function load(selectId?: string) {
    const [nextGallery, nextRuns, nextPacks] = await Promise.all([
      api.applicationGallery(),
      api.economicRuns(),
      api.domainPacks(),
    ])
    setGallery(nextGallery)
    const nextRunItems = nextRuns.items ?? []
    setRuns(nextRunItems)
    setPackages(nextPacks.items ?? [])
    if (!runId && nextRunItems[0]) setRunId(nextRunItems[0].run_id)
    const items = nextGallery.items ?? []
    const chosen = items.find((item: Row) => item.install_id === selectId) ?? items[0] ?? null
    setSelected(chosen)
    if (!chosen) setExecution(null)
  }

  useEffect(() => {
    load().catch((caught: Error) => setError(caught.message))
    // Initial load only; subsequent actions refresh explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function importPackage(file: File | undefined) {
    if (!file) return
    setBusy('import'); setError(null); setMessage(null)
    try {
      const encoded = await readBase64(file)
      const installed = await api.applicationInstall({ package_base64: encoded })
      await load(installed.install_id)
      setMessage(`Installed ${installed.application?.name ?? installed.application_id} ${installed.version}. Integrity checked; publisher is unsigned.`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function exportRun() {
    if (!runId) return
    setBusy('export'); setError(null); setMessage(null)
    try {
      const built = await api.applicationExport({ run_id: runId })
      saveBlob(base64Bytes(built.package_base64), `${built.application_id}-${built.version}.atlas`)
      setMessage(`Built ${built.package_id}. SHA-256 ${built.package_sha256.slice(0, 16)}… · ${built.reproducibility.replaceAll('_', ' ')}.`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function inspect(installId: string) {
    setBusy('open'); setError(null); setMessage(null)
    try {
      const opened = await api.applicationOpen(installId)
      setSelected(opened)
      setExecution(null)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function execute() {
    if (!selected) return
    setBusy('execute'); setError(null); setMessage(null)
    try {
      const result = await api.applicationExecute(selected.install_id)
      setExecution(result)
      setMessage(result.reproduced
        ? `Reproduced in ${num(result.duration_ms, 1)} ms through the installed Atlas runtime.`
        : `Execution status: ${result.status}. No result was promoted.`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function verify() {
    if (!selected) return
    setBusy('verify'); setError(null); setMessage(null)
    try {
      const result = await api.applicationVerify(selected.install_id)
      setMessage(`${result.status.replaceAll('_', ' ')} · ${result.files} files · ${result.signature_status}. ${result.note}`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function fork() {
    if (!selected || !forkName.trim()) return
    setBusy('fork'); setError(null); setMessage(null)
    try {
      const result = await api.applicationFork(selected.install_id, { name: forkName.trim(), version: forkVersion })
      await load(result.fork.install_id)
      setForkName('')
      setMessage(`Forked locally. The comparison keeps unsupported limitations and declarations visible.`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function download() {
    if (!selected) return
    setBusy('download'); setError(null)
    try {
      const blob = await api.applicationDownload(selected.install_id)
      saveBlob(blob, `${selected.application_id}-${selected.version}.atlas`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  async function uninstall() {
    if (!selected || !window.confirm('Remove this installation? The package bytes and install record are deleted; research objects remain.')) return
    setBusy('uninstall'); setError(null); setMessage(null)
    try {
      const result = await api.applicationUninstall(selected.install_id)
      await load()
      setMessage(`Uninstalled ${result.application_id} ${result.version}. Research objects were retained.`)
    } catch (caught) { setError((caught as Error).message) } finally { setBusy(null) }
  }

  const items = gallery?.items ?? []
  const app = selected?.application ?? {}
  const manifest = selected?.manifest ?? {}

  return (
    <div className="page apps-page">
      <div className="section-header">
        <div>
          <div className="eyebrow">Research platform · Installed applications</div>
          <h1>Portable research, without executable strangers</h1>
          <p className="section-detail">
            Packages carry a declarative application, approved data snapshots and their rights.
            Installation never runs third-party code; execution dispatches only to Atlas runtimes.
          </p>
        </div>
        <div className="section-actions">
          <Link className="button" to="/lab/economic">Economic lab</Link>
          <Badge tone="neutral">Local gallery</Badge>
          <Badge tone="warn">Unsigned packages</Badge>
        </div>
      </div>

      {error && <div className="banner banner-warn error-text" data-testid="apps-error">{error}</div>}
      {message && <div className="banner banner-info" data-testid="apps-message">{message}</div>}

      <div className="apps-io-grid">
        <section className="card">
          <SectionHeader eyebrow="Bring your own" title="Install a .atlas package"
            detail="Validated, path-safe, hash-checked and transactional. Only JSON, CSV, Markdown and text payloads are accepted." />
          <label className="apps-file">
            <span>{busy === 'import' ? 'Validating package…' : 'Choose a package file'}</span>
            <input type="file" accept=".atlas,application/zip" data-testid="apps-file"
              onChange={(event) => void importPackage(event.target.files?.[0])} />
          </label>
          <p className="notice small">
            An unsigned package proves that its bytes are internally consistent. It does not prove who
            built it. Atlas has no signature verifier and will not pretend otherwise.
          </p>
        </section>

        <section className="card">
          <SectionHeader eyebrow="Export from evidence" title="Package a saved economic study"
            detail="The real 2023 EIA/NOAA panel, association result and hypothetical scenario travel together with their limitations." />
          <div className="apps-export">
            <label>Saved analysis
              <select className="field" value={runId} onChange={(event) => setRunId(event.target.value)}>
                {runs.length === 0 && <option value="">No saved analyses</option>}
                {runs.map((run) => (
                  <option key={run.run_id} value={run.run_id}>
                    {run.run_id} · R² {num(run.test_r2, 3)}
                  </option>
                ))}
              </select>
            </label>
            <button className="button button-primary" disabled={!runId || busy !== null}
              onClick={() => void exportRun()} data-testid="apps-export">
              {busy === 'export' ? 'Building deterministic package…' : 'Build and download'}
            </button>
          </div>
          <p className="notice small">
            Source rights are checked on the backend before packaging. Restricted or
            user-responsibility data fails closed; a UI warning is not an enforcement boundary.
          </p>
        </section>
      </div>

      <section className="card" data-testid="apps-gallery">
        <SectionHeader eyebrow="Local gallery" title="Installed products"
          detail={`${gallery?.count ?? 0} installation(s) · ${gallery?.pack_count ?? 0} declarative domain pack(s)`}
          actions={<Badge tone="neutral">No central marketplace</Badge>} />
        {items.length === 0 ? (
          <div className="apps-empty">
            <strong>No installed applications.</strong>
            <span>Install the flagship weather-to-demand study or build a package from a saved analysis.</span>
          </div>
        ) : (
          <div className="apps-grid">
            {items.map((item: Row) => (
              <button className={`app-tile ${selected?.install_id === item.install_id ? 'is-active' : ''}`}
                key={item.install_id} onClick={() => void inspect(item.install_id)} data-testid="app-tile">
                <div className="app-tile-head">
                  <span className="eyebrow">{item.application_id}</span>
                  <Badge tone={item.status === 'installed' ? 'positive' : 'warn'}>{item.status}</Badge>
                </div>
                <strong>{item.application?.name}</strong>
                <span className="muted small">{item.application?.description}</span>
                <div className="app-tile-meta">
                  <span className="mono">v{item.version}</span>
                  <span>{item.reproducibility?.replaceAll('_', ' ')}</span>
                  <span>{item.signature_status}</span>
                </div>
              </button>
            ))}
          </div>
        )}
        {packages.length > 0 && (
          <div className="apps-packs">
            <h4>Domain packs</h4>
            {packages.map((pack: Row) => (
              <div key={`${pack.pack_id}-${pack.version}`}>
                <strong>{pack.manifest?.name ?? pack.pack_id}</strong>
                <span className="muted small"> · v{pack.version} · {pack.applications?.length ?? 0} app(s) · declarative only</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {selected && (
        <section className="card apps-detail" data-testid="app-detail">
          <SectionHeader eyebrow={`Installed ${selected.installed_at}`} title={app.name}
            detail={`${selected.application_id} · v${selected.version} · publisher ${selected.publisher_id}`}
            actions={<Badge tone="warn">{selected.signature_status}</Badge>} />

          <div className="apps-detail-grid">
            <div>
              <div className="kv">
                <dt>Runtime</dt><dd className="mono">{app.runtime?.model_runtime}</dd>
                <dt>Reproducibility</dt><dd>{selected.reproducibility?.replaceAll('_', ' ')}</dd>
                <dt>Package</dt><dd className="mono break">{selected.package_id}</dd>
                <dt>SHA-256</dt><dd className="mono break">{selected.package_sha256}</dd>
                <dt>Trust</dt><dd>Integrity checked · publisher not authenticated</dd>
                <dt>Research object</dt><dd className="mono">{selected.object_id}</dd>
              </div>
              <div className="apps-actions">
                <button className="button button-primary" onClick={() => void execute()} disabled={busy !== null} data-testid="app-execute">
                  {busy === 'execute' ? 'Reproducing…' : 'Execute package'}
                </button>
                <button className="button" onClick={() => void verify()} disabled={busy !== null}>Verify integrity</button>
                <button className="button" onClick={() => void download()} disabled={busy !== null}>Download</button>
                <button className="button" onClick={() => void uninstall()} disabled={busy !== null}>Uninstall</button>
              </div>
            </div>
            <div>
              <h4>Source rights</h4>
              <div className="apps-rights">
                {(app.sources ?? []).map((source: Row) => (
                  <div key={source.source_id}>
                    <strong>{source.name}</strong>
                    <span className="muted small">{source.source_id} · {source.license} · {source.redistribution}</span>
                    <Badge tone={source.redistribution === 'permitted' ? 'positive' : 'warn'}>{source.redistribution}</Badge>
                  </div>
                ))}
              </div>
              <h4 style={{ marginTop: 12 }}>Declared views</h4>
              <div className="apps-views">{(app.views ?? []).map((view: Row) => (
                <span key={view.id}>{view.title} <code>{view.type}</code></span>
              ))}</div>
            </div>
          </div>

          <div className="apps-limits">
            <h4>Limitations carried by the package</h4>
            {(app.limitations ?? []).map((item: string) => <div key={item}>{item}</div>)}
          </div>

          {execution && (
            <div className="apps-execution" data-testid="app-execution">
              <div className="app-execution-head">
                <Badge tone={execution.reproduced ? 'positive' : 'warn'}>{execution.status}</Badge>
                <span className="muted small">{num(execution.duration_ms, 1)} ms · {execution.runtime}</span>
              </div>
              {execution.analysis ? (
                <div className="apps-exec-metrics">
                  <div><span>Expected RMSE</span><strong>{num(execution.analysis.expected_test_rmse, 2)} MW</strong></div>
                  <div><span>Actual RMSE</span><strong>{num(execution.analysis.actual_test_rmse, 2)} MW</strong></div>
                  <div><span>Expected R²</span><strong>{num(execution.analysis.expected_test_r2, 4)}</strong></div>
                  <div><span>Actual R²</span><strong>{num(execution.analysis.actual_test_r2, 4)}</strong></div>
                  <div><span>Cost delta</span><strong>${num(execution.scenario?.actual_cost_delta_usd, 2)}</strong></div>
                  <div><span>Causal status</span><strong>{execution.analysis.causal_status}</strong></div>
                </div>
              ) : <p className="small">{execution.reason}</p>}
              <p className="notice small">
                Execution dispatches to Atlas's existing model and FEC runtimes. Package-provided code is never imported.
              </p>
            </div>
          )}

          <div className="apps-fork">
            <label>Fork name<input className="field" value={forkName} onChange={(event) => setForkName(event.target.value)} placeholder="Local research variant" /></label>
            <label>Version<input className="field mono" value={forkVersion} onChange={(event) => setForkVersion(event.target.value)} /></label>
            <button className="button" onClick={() => void fork()} disabled={busy !== null || !forkName.trim()}>Fork locally</button>
          </div>
          <details className="apps-manifest">
            <summary>Inspect package manifest and file hashes</summary>
            <pre>{JSON.stringify(manifest, null, 2)}</pre>
          </details>
        </section>
      )}

      <section className="card apps-security">
        <SectionHeader eyebrow="Security boundary" title="What installation does not do"
          detail="A package is not a plugin. The absent capabilities are part of the contract." />
        <div className="apps-security-grid">
          <div><strong>No arbitrary code</strong><span>No Python, JavaScript, shell, SQL or native extension is executed.</span></div>
          <div><strong>No network</strong><span>Installation and execution make no outbound request from package content.</span></div>
          <div><strong>No persistence escape</strong><span>Declared writes stay in Atlas application tables and research objects.</span></div>
          <div><strong>No signature claim</strong><span>SHA-256 integrity and deterministic bytes are not publisher identity.</span></div>
        </div>
      </section>
    </div>
  )
}
