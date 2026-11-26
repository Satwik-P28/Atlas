import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

interface Hit {
  issuer_id: string
  label: string
  cik: string | null
  tickers: string[]
}

/** Shared instrument search. Unresolved text stays unresolved: Atlas never invents a match. */
export default function SecuritySearch({
  onSelect,
  className = '',
}: {
  onSelect?: (issuerId: string) => void
  className?: string
}) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<Hit[]>([])
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const text = query.trim()
    if (!text) {
      setHits([])
      return
    }
    let cancelled = false
    setSearching(true)
    const handle = window.setTimeout(() => {
      api
        .search(text)
        .then((response) => {
          if (cancelled) return
          setHits(response.items)
          setError(null)
          setOpen(true)
        })
        .catch((caught: Error) => {
          if (!cancelled) setError(caught.message)
        })
        .finally(() => {
          if (!cancelled) setSearching(false)
        })
    }, 170)
    return () => {
      cancelled = true
      window.clearTimeout(handle)
    }
  }, [query])

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  function choose(hit: Hit) {
    setOpen(false)
    setQuery('')
    if (onSelect) onSelect(hit.issuer_id)
    else navigate(`/companies/${hit.issuer_id}`)
  }

  return (
    <div className={`std-search ${className}`} ref={boxRef}>
      <form
        role="search"
        onSubmit={(event) => {
          event.preventDefault()
          if (hits[0]) choose(hits[0])
        }}
      >
        <input
          aria-label="Search securities"
          placeholder="Search ticker, company or CIK…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => hits.length && setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setOpen(false)
              setQuery('')
            }
          }}
          autoComplete="off"
          spellCheck={false}
        />
      </form>
      {open && (searching || error || hits.length > 0 || query.trim()) && (
        <div className="search-results">
          {searching && <div className="search-empty">Searching…</div>}
          {error && <div className="search-empty error-text">{error}</div>}
          {!searching && !error && !hits.length && (
            <div className="search-empty">No instrument matches “{query}”. Atlas does not invent one.</div>
          )}
          {hits.map((hit) => (
            <button key={hit.issuer_id} className="search-hit" onClick={() => choose(hit)}>
              <span>{hit.label}</span>
              <span className="muted small">{[hit.tickers.join(' · '), hit.cik].filter(Boolean).join(' · ')}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
