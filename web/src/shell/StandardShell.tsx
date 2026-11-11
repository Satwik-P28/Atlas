import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { api } from '../api'
import SecuritySearch from '../components/SecuritySearch'
import { useAsync, useSettings } from '../state'

const PRIMARY = [
  { to: '/', label: 'Markets', end: true },
  { to: '/companies', label: 'Securities' },
  { to: '/research', label: 'Research' },
  { to: '/equity', label: 'Memos' },
  { to: '/screeners', label: 'Screeners' },
  { to: '/studio', label: 'Models' },
  { to: '/lab/institutional', label: 'Portfolios' },
  { to: '/workspaces', label: 'Workspaces' },
  { to: '/lab', label: 'Quant lab' },
  { to: '/watchlists', label: 'Watchlists' },
]

/** Standard: a research desk. Top navigation, one guided workflow per page,
 * comfortable density, and the evidence caveats kept in the open rather than
 * pushed into a settings pane. */
export default function StandardShell({ children }: { children: ReactNode }) {
  const { theme, mode, setTheme, setMode, apiError } = useSettings()
  const health = useAsync(() => api.health(), [])
  const status = health.data as { status?: string; evidence?: number; bars?: number } | null

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
    </div>
  )
}
