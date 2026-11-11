import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAsync, useSettings } from '../state'
import CommandPalette from '../terminal/command/CommandPalette'
import type { AtlasCommand, CommandContext } from '../terminal/command/registry'
import { cutoffLabel, linkSummary, resolveInstrument, type LinkGroup } from '../terminal/links'
import { LinkProvider, useLinks } from '../terminal/linkContext'

const RAIL = [
  { to: '/workstation', glyph: '▤', label: 'Desk' },
  { to: '/companies', glyph: '⌕', label: 'Inst' },
  { to: '/research', glyph: '◷', label: 'Rsrch' },
  { to: '/equity', glyph: '✎', label: 'Memos' },
  { to: '/studio', glyph: '◈', label: 'Model' },
  { to: '/lab', glyph: '∑', label: 'Quant' },
  { to: '/lab/institutional', glyph: '▥', label: 'Port' },
  { to: '/workspaces', glyph: '⊞', label: 'Saved' },
]

/** Advanced: a workstation. Command header, icon rail, dockable desk, context
 * inspector and a status bar that states the cutoff and data condition. */
export default function AdvancedShell({ children }: { children: ReactNode }) {
  return (
    <LinkProvider>
      <AdvancedShellInner>{children}</AdvancedShellInner>
    </LinkProvider>
  )
}

function AdvancedShellInner({ children }: { children: ReactNode }) {
  const { theme, mode, setTheme, setMode } = useSettings()
  const links = useLinks()
  const location = useLocation()
  const navigate = useNavigate()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)

  const companies = useAsync(() => api.companies(), [])
  const workspaces = useAsync(() => api.workspaces(), [])
  const health = useAsync(() => api.health(), [])
  const schema = useAsync(() => api.schema(), [])

  const isDesk = location.pathname.startsWith('/workstation')
  const selection = resolveInstrument(links.state, links.state.activeGroup)
  const instrument = companies.data?.items.find((item) => item.issuer_id === selection.issuerId)

  const commandContext = useMemo<CommandContext>(
    () => ({
      instruments: (companies.data?.items ?? []).map((item) => ({
        issuer_id: item.issuer_id,
        legal_name: item.legal_name,
        tickers: item.securities.map((security) => security.tickers[0]?.ticker).filter((ticker): ticker is string => Boolean(ticker)),
      })),
      workspaces: (workspaces.data?.items ?? []).map((workspace) => ({
        workspace_id: workspace.workspace_id,
        name: workspace.name,
      })),
    }),
    [companies.data, workspaces.data],
  )

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null
      const typing = target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
      const meta = event.metaKey || event.ctrlKey
      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
        return
      }
      if (meta && event.shiftKey && event.key.toLowerCase() === 'p') {
        event.preventDefault()
        setPaletteOpen(true)
        return
      }
      if (meta && event.key.toLowerCase() === 's') {
        event.preventDefault()
        window.dispatchEvent(new Event('atlas:save'))
        return
      }
      if (event.key === '/' && !typing) {
        event.preventDefault()
        setPaletteOpen(true)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  function openPanel(panel: string) {
    if (!isDesk) navigate('/workstation')
    window.setTimeout(() => window.dispatchEvent(new CustomEvent('atlas:panel', { detail: panel })), 30)
  }

  function runCommand(command: AtlasCommand) {
    switch (command.id) {
      case 'instrument': {
        const company = companies.data?.items.find((item) => item.issuer_id === command.issuerId)
        links.select(links.state.activeGroup, command.issuerId, company?.securities[0]?.security_id ?? null)
        if (!isDesk) navigate('/workstation')
        if (command.panel) {
          window.setTimeout(() => window.dispatchEvent(new CustomEvent('atlas:panel', { detail: command.panel })), 30)
        }
        break
      }
      case 'panel':
        openPanel(command.panel)
        break
      case 'workspace':
        navigate(`/workstation/${command.workspaceId}`)
        break
      case 'asof':
        links.setAsOf(command.asOf)
        break
      case 'mode':
        links.setMode(command.mode)
        break
      case 'save':
        window.dispatchEvent(new Event('atlas:save'))
        break
      case 'reset':
        window.dispatchEvent(new Event('atlas:reset'))
        break
      case 'help':
        setPaletteOpen(true)
        break
      default:
        break
    }
  }

  const status = health.data as { status?: string; evidence?: number; bars?: number; schema_version?: number } | null
  const online = status?.status === 'ok'
  // Before the first response arrives Atlas has not checked the database, so it must
  // not assert "offline" or a count of zero: that would be an unverified claim.
  const healthState = health.loading ? 'checking' : online ? 'online' : 'offline'
  const healthClass = health.loading ? '' : online ? 'is-ok' : 'is-bad'

  return (
    <div className={`adv-shell ${inspectorOpen ? 'is-inspector-open' : ''}`}>
      <header className="adv-header">
        <div className="adv-brand">
          ATLAS <small>quant workstation</small>
        </div>
        <button className="adv-command-trigger" onClick={() => setPaletteOpen(true)} aria-label="Open command palette">
          <span>{instrument ? instrument.securities[0]?.tickers[0]?.ticker ?? instrument.legal_name : 'Select instrument'}</span>
          <span className="tp-secondary">·</span>
          <span>{isDesk ? 'desk' : location.pathname}</span>
          <kbd>⌘K</kbd>
        </button>
        <div className="adv-head-facts">
          <div className="adv-fact">
            <span>Cutoff</span>
            <strong title={links.state.asOf ?? 'latest available'}>{cutoffLabel(links.state)}</strong>
          </div>
          <div className="adv-fact">
            <span>Mode</span>
            <strong>{links.state.mode === 'public_available' ? 'public' : 'ingested'}</strong>
          </div>
          <div className="adv-fact">
            <span>Data</span>
            <strong className={healthClass}>
              {health.loading ? 'checking…' : online ? `${(status?.evidence ?? 0).toLocaleString()} ev` : 'offline'}
            </strong>
          </div>
        </div>
        <div className="adv-head-actions">
          <button
            className="wb-icon-button"
            aria-label={inspectorOpen ? 'Hide inspector' : 'Show inspector'}
            title="Context inspector"
            onClick={() => setInspectorOpen((open) => !open)}
          >
            ⇥
          </button>
          <div className="segmented" role="group" aria-label="Interface mode">
            {(['standard', 'advanced'] as const).map((option) => (
              <button
                key={option}
                className={mode === option ? 'is-selected' : ''}
                onClick={() => setMode(option)}
              >
                {option === 'standard' ? 'Std' : 'Adv'}
              </button>
            ))}
          </div>
          <button
            className="wb-icon-button"
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            {theme === 'dark' ? '☾' : '☀'}
          </button>
        </div>
      </header>

      <nav className="adv-rail" aria-label="Workstation">
        {RAIL.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `adv-rail-link ${isActive ? 'is-active' : ''}`}
            title={item.label}
          >
            <span className="rail-glyph" aria-hidden>
              {item.glyph}
            </span>
            {item.label}
          </NavLink>
        ))}
        <span className="adv-rail-spacer" />
        <button className="adv-rail-link" title="Command palette" onClick={() => setPaletteOpen(true)}>
          <span className="rail-glyph" aria-hidden>
            ⌘
          </span>
          Cmd
        </button>
      </nav>

      <main className={`adv-main ${isDesk ? 'is-desk' : ''}`}>{children}</main>

      <aside className="adv-inspector" aria-label="Context inspector">
        <section className="insp-section">
          <div className="insp-title">
            Link groups
            <span className="tp-badge">{links.state.activeGroup}</span>
          </div>
          <div className="tp-toolbar">
            {(['A', 'B', 'C', 'D'] as LinkGroup[]).map((group) => (
              <button
                key={group}
                className={`button ${links.state.activeGroup === group ? 'button-primary' : ''}`}
                onClick={() => links.setGroup(group)}
                title={`Drive link group ${group}`}
              >
                {group}
              </button>
            ))}
          </div>
          <label className="inline-field small">
            Instrument
            <select
              className="field"
              value={selection.issuerId ?? ''}
              onChange={(event) => {
                const company = companies.data?.items.find((item) => item.issuer_id === event.target.value)
                links.select(links.state.activeGroup, event.target.value || null, company?.securities[0]?.security_id ?? null)
              }}
            >
              <option value="">— none —</option>
              {(companies.data?.items ?? []).map((item) => (
                <option key={item.issuer_id} value={item.issuer_id}>
                  {item.securities[0]?.tickers[0]?.ticker ?? item.legal_name}
                </option>
              ))}
            </select>
          </label>
          <dl className="insp-kv">
            <dt>security</dt>
            <dd>{selection.securityId ?? '—'}</dd>
            <dt>issuer</dt>
            <dd>{selection.issuerId ?? '—'}</dd>
          </dl>
        </section>

        <section className="insp-section">
          <div className="insp-title">Point in time</div>
          <label className="inline-field small">
            Information cutoff
            <input
              type="date"
              className="field"
              value={links.state.asOf ?? ''}
              onChange={(event) => links.setAsOf(event.target.value || null)}
            />
          </label>
          <label className="inline-field small">
            Availability
            <select
              className="field"
              value={links.state.mode}
              onChange={(event) =>
                links.setMode(event.target.value === 'atlas_ingested' ? 'atlas_ingested' : 'public_available')
              }
            >
              <option value="public_available">public availability</option>
              <option value="atlas_ingested">Atlas ingestion time</option>
            </select>
          </label>
          <p className="insp-hint">
            Evidence unavailable at this cutoff is excluded, not backfilled. Panels show the active policy.
          </p>
        </section>

        <section className="insp-section">
          <div className="insp-title">Registry</div>
          <dl className="insp-kv">
            <dt>terminal</dt>
            <dd>{String((schema.data as Record<string, unknown>)?.terminal_schema ?? '—')}</dd>
            <dt>workspace</dt>
            <dd>{String((schema.data as Record<string, unknown>)?.workspace_layout_schema ?? '—')}</dd>
            <dt>schema</dt>
            <dd>{String(status?.schema_version ?? '—')}</dd>
          </dl>
        </section>

        <section className="insp-section">
          <div className="insp-title">Keys</div>
          <ul className="insp-list">
            <li>
              <span className="tp-mono">⌘K</span> command palette
            </li>
            <li>
              <span className="tp-mono">/</span> palette from anywhere
            </li>
            <li>
              <span className="tp-mono">⌘S</span> save layout
            </li>
            <li>
              <span className="tp-mono">Esc</span> close overlay
            </li>
          </ul>
        </section>
      </aside>

      <footer className="adv-status">
        <span className={healthClass}>
          {healthState === 'checking'
            ? 'checking database…'
            : online
              ? 'evidence online'
              : health.error
                ? 'database unavailable'
                : 'database missing'}
        </span>
        {online && <span>{(status?.evidence ?? 0).toLocaleString()} evidence</span>}
        {online && <span>{(status?.bars ?? 0).toLocaleString()} bars</span>}
        <span className="adv-status-spacer" />
        <span>{linkSummary(links.state)}</span>
      </footer>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        context={commandContext}
        onRun={runCommand}
      />
    </div>
  )
}
