import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAsync } from '../state'
import { fmtCompact, fmtDate, fmtSignedPct, toneForNumber } from '../format'
import { Badge, EmptyState, ErrorState, Loading, SectionHeader } from '../components/ui'
import type { Watchlist } from '../types'

export default function Watchlists() {
  const lists = useAsync(() => api.watchlists(), [])
  const companies = useAsync(() => api.companies(), [])
  const markets = useAsync(() => api.markets(), [])
  const [selected, setSelected] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [pendingSecurity, setPendingSecurity] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    if (!selected && lists.data?.items.length) setSelected(lists.data.items[0].watchlist_id)
  }, [lists.data, selected])

  const current: Watchlist | null = useMemo(
    () => lists.data?.items.find((item) => item.watchlist_id === selected) ?? null,
    [lists.data, selected],
  )
  const priceBySecurity = useMemo(() => {
    const map = new Map<string, { close: number; change: number | null; date: string; status: string }>()
    markets.data?.items.forEach((item) =>
      map.set(item.security_id, { close: item.last_close, change: item.change_1d, date: item.last_bar_date, status: item.data_status }),
    )
    return map
  }, [markets.data])

  const securityOptions = useMemo(
    () =>
      (companies.data?.items ?? []).flatMap((company) =>
        company.securities.map((security) => ({
          securityId: security.security_id,
          label: `${security.tickers[0]?.ticker ?? security.class_designation} — ${company.legal_name}${company.securities.length > 1 ? ` (${security.class_designation})` : ''}`,
        })),
      ),
    [companies.data],
  )

  async function run(action: () => Promise<Watchlist>) {
    setBusy(true)
    setError(null)
    try {
      const updated = await action()
      lists.setData((previous) => {
        if (!previous) return { items: [updated] }
        const exists = previous.items.some((item) => item.watchlist_id === updated.watchlist_id)
        return {
          items: exists
            ? previous.items.map((item) => (item.watchlist_id === updated.watchlist_id ? updated : item))
            : [...previous.items, updated],
        }
      })
      setSelected(updated.watchlist_id)
    } catch (caught) {
      setError(caught as Error)
    } finally {
      setBusy(false)
    }
  }

  async function create() {
    if (!name.trim()) return
    await run(() => api.createWatchlist({ name: name.trim() }))
    setName('')
  }

  return (
    <div className="page">
      <SectionHeader
        eyebrow="Watchlists"
        title="Saved securities"
        detail="Items reference stable security ids, not tickers, so a symbol reassignment cannot silently change a saved list. Stored in the local database."
        actions={<Badge tone="neutral">{lists.data?.items.length ?? 0} lists</Badge>}
      />
      {lists.loading && <Loading label="Loading watchlists" />}
      {lists.error && <ErrorState error={lists.error} onRetry={lists.reload} />}
      {error && <ErrorState error={error} />}

      <div className="watchlist-layout">
        <aside className="card watchlist-nav">
          <div className="inline-form">
            <input
              className="field"
              placeholder="New watchlist name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && void create()}
              aria-label="New watchlist name"
            />
            <button className="button button-primary" onClick={create} disabled={busy || !name.trim()}>
              Create
            </button>
          </div>
          <ul className="list">
            {lists.data?.items.map((item) => (
              <li key={item.watchlist_id}>
                <button
                  className={`list-button ${item.watchlist_id === selected ? 'is-active' : ''}`}
                  onClick={() => setSelected(item.watchlist_id)}
                >
                  <span>{item.name}</span>
                  <span className="muted small">{item.items.length}</span>
                </button>
              </li>
            ))}
          </ul>
          {lists.data && lists.data.items.length === 0 && <p className="muted small">No watchlists yet.</p>}
        </aside>

        <section className="card">
          {!current && <EmptyState title="Select a watchlist" detail="Create one on the left, then add securities." />}
          {current && (
            <>
              <div className="toolbar">
                <h3>{current.name}</h3>
                <div className="toolbar-right">
                  <button
                    className="button"
                    onClick={() => {
                      const next = window.prompt('Rename watchlist', current.name)
                      if (next && next !== current.name) void run(() => api.renameWatchlist(current.watchlist_id, { name: next }))
                    }}
                  >
                    Rename
                  </button>
                  <button
                    className="button button-danger"
                    onClick={() => {
                      if (!window.confirm(`Delete “${current.name}”? This cannot be undone.`)) return
                      void api.deleteWatchlist(current.watchlist_id).then(() => {
                        lists.setData((previous) => previous && { items: previous.items.filter((item) => item.watchlist_id !== current.watchlist_id) })
                        setSelected(null)
                      })
                    }}
                  >
                    Delete
                  </button>
                </div>
              </div>
              <div className="inline-form">
                <select className="field" value={pendingSecurity} onChange={(event) => setPendingSecurity(event.target.value)} aria-label="Security to add">
                  <option value="">Add a security…</option>
                  {securityOptions.map((option) => (
                    <option key={option.securityId} value={option.securityId}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <button
                  className="button"
                  disabled={!pendingSecurity || busy}
                  onClick={async () => {
                    await run(() => api.addWatchlistItem(current.watchlist_id, pendingSecurity))
                    setPendingSecurity('')
                  }}
                >
                  Add
                </button>
              </div>
              {current.items.length === 0 ? (
                <p className="muted">This watchlist is empty.</p>
              ) : (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th>Company</th>
                        <th className="numeric">Last</th>
                        <th className="numeric">1 day</th>
                        <th>Session</th>
                        <th>Source</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {current.items.map((item) => {
                        const price = priceBySecurity.get(item.security_id)
                        return (
                          <tr key={item.security_id}>
                            <td className="mono">
                              <Link className="ticker-link" to={`/companies/${item.issuer_id}`}>
                                {item.ticker ?? '—'}
                              </Link>
                            </td>
                            <td>{item.legal_name}</td>
                            <td className="numeric mono">{price ? fmtCompact(price.close) : '—'}</td>
                            <td className={`numeric mono ${toneForNumber(price?.change ?? null)}`}>
                              {price?.change == null ? '—' : fmtSignedPct(price.change)}
                            </td>
                            <td className="mono small">{price ? fmtDate(price.date) : '—'}</td>
                            <td>
                              {price?.status === 'synthetic' ? <Badge tone="synthetic">synthetic</Badge> : <Badge tone="accent">reported</Badge>}
                            </td>
                            <td>
                              <button
                                className="link-button small"
                                onClick={() => void run(() => api.removeWatchlistItem(current.watchlist_id, item.security_id))}
                              >
                                remove
                              </button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
