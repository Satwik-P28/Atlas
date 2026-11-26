import { createContext, useContext, useMemo, useReducer, type ReactNode } from 'react'
import { initialLinkState, linkReducer, type LinkAction, type LinkGroup, type LinkState } from './links'

interface LinkContextValue {
  state: LinkState
  dispatch: (action: LinkAction) => void
  select: (group: LinkGroup, issuerId: string | null, securityId: string | null) => void
  setAsOf: (asOf: string | null) => void
  setMode: (mode: LinkState['mode']) => void
  setGroup: (group: LinkGroup) => void
}

const LinkContext = createContext<LinkContextValue | null>(null)

export function LinkProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(linkReducer, undefined, initialLinkState)
  const value = useMemo<LinkContextValue>(
    () => ({
      state,
      dispatch,
      select: (group, issuerId, securityId) => dispatch({ type: 'select', group, issuerId, securityId }),
      setAsOf: (asOf) => dispatch({ type: 'asof', asOf }),
      setMode: (mode) => dispatch({ type: 'mode', mode }),
      setGroup: (group) => dispatch({ type: 'group', group }),
    }),
    [state],
  )
  return <LinkContext.Provider value={value}>{children}</LinkContext.Provider>
}

export function useLinks(): LinkContextValue {
  const context = useContext(LinkContext)
  if (!context) throw new Error('useLinks must be used inside LinkProvider')
  return context
}
