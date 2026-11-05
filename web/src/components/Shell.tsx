import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { fmtCompact } from '../format'
import { useSettings } from '../state'

interface SearchHit {
  issuer_id: string
  label: string
  cik: string | null
  tickers: string[]
}

const NAV = [
  { section: 'Market', items: [{ to: '/', label: 'Markets' }, { to: '/companies', label: 'Companies' }] },
  { section: 'Research', items: [{ to: '/research', label: 'Time machine' }, { to: '/equity', label: 'Equity research' }, { to: '/screeners', label: 'Screeners' }] },
  { section: 'Studio', items: [{ to: '/studio', label: 'Model studio' }, { to: '/lab', label: 'Quant lab' }, { to: '/lab/learning', label: 'Learning lab' }, { to: '/lab/economic', label: 'Economic lab' }] },
  { section: 'Platform', items: [{ to: '/applications', label: 'Applications' }] },
  { section: 'Saved', items: [{ to: '/watchlists', label: 'Watchlists' }] },
]

export default function Shell({ children }: { children: ReactNode }) {
  const { theme, mode, setTheme, setMode, apiError } = useSettings()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [health, setHealth] = useState<{
    evidence?: number; bars?: number; status?: string
    economic_observations?: number; schema_version?: number
  } | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.health().then((payload) => setHealth(payload as typeof health)).catch(() => setHealth(null))
  }, [])

  useEffect(() => {
    const text = query.trim()
    if (text.length < 1) {
      setHits([])
      return
    }
    let cancelled = false
    setSearching(true)
    const handle = window.setTimeout(() => {
      api
        .search(text)
        .then((response) => {
          if (!cancelled) {
            setHits(response.items)
            setSearchError(null)
          }
        })
        .catch((error: Error) => {
          if (!cancelled) setSearchError(error.message)
        })
        .finally(() => {
          if (!cancelled) setSearching(false)
        })
    }, 180)
    return () => {
      cancelled = true
      window.clearTimeout(handle)
    }
  }, [query])

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setHits([])
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const nav = useMemo(() => {
    const items = NAV.flatMap((group) => group.items)
    return mode === 'advanced' ? [...items, { to: '/workspaces', label: 'Workspaces' }] : items
  }, [mode])

  function submitSearch(event: React.FormEvent) {
    event.preventDefault()
    const first = hits[0]
    if (first) {
      setHits([])
      setQuery('')
      navigate(`/companies/${first.issuer_id}`)
    }
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileOpen ? 'is-open' : ''}`}>
        <div className="brand">
          <span className="brand-mark">A</span>
          <div>
            <div className="brand-name">Atlas Quant</div>
            <div className="brand-sub">Evidence terminal</div>
          </div>
        </div>
        <nav className="nav">
          {nav.map((item, index) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) => `nav-link ${isActive ? 'is-active' : ''}`}
            >
              <span className="nav-index">{String(index + 1).padStart(2, '0')}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        {mode === 'advanced' && (
          <div className="sidebar-note">
            <div className="eyebrow">Advanced mode</div>
            <p>Panels, raw as-of controls and provenance tools are unlocked. Results are identical to Standard mode.</p>
          </div>
        )}
        <div className="sidebar-footer">
          <div className="data-pill">
            <span className={`dot ${health?.status === 'ok' ? 'dot-ok' : 'dot-warn'}`} />
            {health?.status === 'ok' ? 'Local evidence online' : 'Database unavailable'}
          </div>
          <div className="muted small">
            {health?.evidence
              ? `${health.evidence.toLocaleString()} evidence records · ${fmtCompact(health.bars ?? 0)} bars`
              : health?.economic_observations
                ? `${health.economic_observations.toLocaleString()} economic observations · schema ${health.schema_version}`
                : 'Run the data builder to populate'}
          </div>
        </div>
      </aside>

      {mobileOpen && <button className="scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}

      <div className="main-area">
        <header className="topbar">
          <button className="icon-button menu-button" aria-label="Open navigation" onClick={() => setMobileOpen(true)}>
            ☰
          </button>
          <div className="search" ref={boxRef}>
            <form onSubmit={submitSearch} role="search">
              <input
                aria-label="Search companies or tickers"
                placeholder="Search company, ticker or CIK…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                autoComplete="off"
              />
              <kbd>/</kbd>
            </form>
            {(hits.length > 0 || searching || searchError) && (
              <div className="search-results">
                {searching && <div className="search-empty">Searching…</div>}
                {searchError && <div className="search-empty error-text">{searchError}</div>}
                {!searching && !searchError && hits.length === 0 && (
                  <div className="search-empty">No company matches “{query}”. Atlas does not invent a match.</div>
                )}
                {hits.map((hit) => (
                  <button
                    key={hit.issuer_id}
                    className="search-hit"
                    onClick={() => {
                      setHits([])
                      setQuery('')
                      navigate(`/companies/${hit.issuer_id}`)
                    }}
                  >
                    <span>{hit.label}</span>
                    <span className="muted small">{[hit.tickers.join(' · '), hit.cik].filter(Boolean).join(' · ')}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="topbar-actions">
            <div className="segmented" role="group" aria-label="Interface mode">
              {(['standard', 'advanced'] as const).map((option) => (
                <button
                  key={option}
                  className={mode === option ? 'is-selected' : ''}
                  onClick={() => setMode(option)}
                  title={option === 'advanced' ? 'Advanced research workspace' : 'Guided research interface'}
                >
                  {option === 'standard' ? 'Standard' : 'Advanced'}
                </button>
              ))}
            </div>
            <button
              className="icon-button"
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              title="Toggle theme"
            >
              {theme === 'dark' ? '☾' : '☀'}
            </button>
          </div>
        </header>
        {apiError && (
          <div className="banner banner-warn">
            Preferences are not persisting: {apiError}. Research data is unaffected.
          </div>
        )}
        <main className="content">{children}</main>
        <footer className="footer">
          <span>SEC fundamentals are public-domain filings. Market prices are labelled SYNTHETIC unless imported from a licensed source.</span>
          <Link to="/research" className="footer-link">
            Point-in-time policy
          </Link>
        </footer>
      </div>
    </div>
  )
}
