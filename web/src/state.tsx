import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from './api'
import type { Mode, Theme } from './types'

interface SettingsState {
  theme: Theme
  mode: Mode
  loaded: boolean
  apiError: string | null
  setTheme: (theme: Theme) => void
  setMode: (mode: Mode) => void
}

const SettingsContext = createContext<SettingsState | null>(null)

function readLocal<T extends string>(key: string, fallback: T): T {
  try {
    const stored = window.localStorage.getItem(`atlas.${key}`)
    return (stored as T) || fallback
  } catch {
    return fallback
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => readLocal<Theme>('theme', 'dark'))
  const [mode, setModeState] = useState<Mode>(() => readLocal<Mode>('mode', 'standard'))
  const [loaded, setLoaded] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .settings()
      .then((response) => {
        if (cancelled) return
        const storedTheme = response.values.theme
        const storedMode = response.values.mode
        if (storedTheme === 'dark' || storedTheme === 'light') setThemeState(storedTheme)
        if (storedMode === 'standard' || storedMode === 'advanced') setModeState(storedMode)
        setLoaded(true)
      })
      .catch((error: Error) => {
        if (cancelled) return
        setApiError(error.message)
        setLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      window.localStorage.setItem('atlas.theme', theme)
    } catch {
      /* storage unavailable: the server preference still applies for this session */
    }
  }, [theme])

  const persist = useCallback((key: string, value: unknown) => {
    api.setSetting(key, value).catch(() => {
      // A failed preference write must not block research; the local value stays.
    })
  }, [])

  const setTheme = useCallback(
    (next: Theme) => {
      setThemeState(next)
      persist('theme', next)
    },
    [persist],
  )

  const setMode = useCallback(
    (next: Mode) => {
      setModeState(next)
      try {
        window.localStorage.setItem('atlas.mode', next)
      } catch {
        /* ignore */
      }
      persist('mode', next)
    },
    [persist],
  )

  const value = useMemo(
    () => ({ theme, mode, loaded, apiError, setTheme, setMode }),
    [theme, mode, loaded, apiError, setTheme, setMode],
  )
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

export function useSettings(): SettingsState {
  const context = useContext(SettingsContext)
  if (!context) throw new Error('useSettings must be used inside SettingsProvider')
  return context
}

/** Small async hook with explicit loading/error/empty states. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    loader()
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((caught: Error) => {
        if (!cancelled) setError(caught)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { data, error, loading, reload: () => setNonce((n) => n + 1), setData }
}
