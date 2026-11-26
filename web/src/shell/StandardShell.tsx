import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { api } from '../api'
import SecuritySearch from '../components/SecuritySearch'
import { useAsync, useSettings } from '../state'
import CommandPalette from '../terminal/command/CommandPalette'
import { actionPath, loadRecents, recordRecent, type PaletteEntity } from '../terminal/command/indexSearch'
import type { AtlasCommand, CommandContext } from '../terminal/command/registry'

const PRIMARY = [
  { to: '/', label: 'Markets', end: true },
  { to: '/companies', label: 'Securities' },
  { to: '/research', label: 'Research' },
  { to: '/answers', label: 'Answers' },
  { to: '/compare', label: 'Compare' },
  { to: '/filings', label: 'Filings' },
  { to: '/equity', label: 'Memos' },
  { to: '/screeners', label: 'Screeners' },
  { to: '/studio', label: 'Models' },
  { to: '/lab/institutional', label: 'Portfolios' },
  { to: '/workspaces', label: 'Workspaces' },
  { to: '/data', label: 'Data' },
]

/** Standard: a research desk. Top navigation, one guided workflow per page,
 * comfortable density, and the evidence caveats kept in the open rather than
 * pushed into a settings pane. */
export default function StandardShell({ children }: { children: ReactNode }) {
  const { theme, mode, setTheme, setMode, apiError } = useSettings()
  const navigate = useNavigate()
  const health = useAsync(() => api.health(), [])
  const companies = useAsync(() => api.companies(), [])
  const workspaces = useAsync(() => api.workspaces(), [])
  const index = useAsync(() => api.commandIndex(), [])
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [recents, setRecents] = useState<PaletteEntity[]>(() => loadRecents())
  const status = health.data as { status?: string; evidence?: number; bars?: number } | null

  const commandContext = useMemo<CommandContext>(
    () => ({
      instruments: (companies.data?.items ?? []).map((item) => ({
        issuer_id: item.issuer_id,
        legal_name: item.legal_name,
        tickers: item.securities
          .map((security) => security.tickers[0]?.ticker)
          .filter((ticker): ticker is string => Boolean(ticker)),
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
      if ((meta && event.key.toLowerCase() === 'k') || (event.key === '/' && !typing)) {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  function runCommand(command: AtlasCommand) {
    switch (command.id) {
      case 'instrument':
        navigate(`/companies/${encodeURIComponent(command.issuerId)}`)
        break
      case 'workspace':
        navigate(`/workstation/${encodeURIComponent(command.workspaceId)}`)
        break
      case 'asof':
      case 'mode':
        navigate('/workstation')
        break
      case 'panel':
        navigate('/workstation')
        break
      default:
        break
    }
  }

  function runEntity(entity: PaletteEntity) {
    const path = actionPath(entity.action)
    setRecents(recordRecent(entity))
    if (path) navigate(path)
  }

  return (
    <div className="std-shell">
      <header className="std-header">
        <div className="std-header-row">
          <Link className="std-brand" to="/">
            ATLAS <small>research terminal</small>
          </Link>
          <nav className="std-nav" aria-label="Primary">
            {PRIMARY.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? 'is-active' : '')}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="std-utilities">
            <button
              className="button"
              onClick={() => setPaletteOpen(true)}
              aria-label="Open command palette"
              title="Companies, concepts, filings, questions, models, strategies, research, experiments, workspaces and packages"
            >
              Search ⌘K
            </button>
            <span className="small muted" title={status?.status === 'ok' ? 'Evidence database online' : 'Database unavailable'}>
              <span className={`dot ${status?.status === 'ok' ? 'dot-ok' : 'dot-warn'}`} />{' '}
              {health.loading
                ? 'checking evidence…'
                : status?.evidence
                  ? `${(status.evidence as number).toLocaleString()} evidence`
                  : 'no database'}
            </span>
            <SecuritySearch />
            <div className="segmented" role="group" aria-label="Interface mode">
              {(['standard', 'advanced'] as const).map((option) => (
                <button
                  key={option}
                  className={mode === option ? 'is-selected' : ''}
                  onClick={() => setMode(option)}
                  title={option === 'advanced' ? 'Open the quantitative workstation' : 'Guided research interface'}
                >
                  {option === 'standard' ? 'Standard' : 'Advanced'}
                </button>
              ))}
            </div>
            <button
              className="icon-button"
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? '☾' : '☀'}
            </button>
          </div>
        </div>
        {apiError && (
          <div className="banner banner-warn">Preferences are not persisting: {apiError}. Research data is unaffected.</div>
        )}
      </header>
      <div className="std-content">{children}</div>
      <footer className="std-footer">
        <span>
          SEC fundamentals are public-domain filings. Atlas bundles no market prices; price analysis appears only after
          an authorised import, and exports respect the rights of every cited source.
        </span>
        <Link to="/research">Point-in-time policy</Link>
      </footer>
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        context={commandContext}
        index={index.data ?? null}
        recents={recents}
        onRun={runCommand}
        onRunEntity={runEntity}
      />
    </div>
  )
}
