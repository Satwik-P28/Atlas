/** Linked analytical context for the workstation.
 *
 * Panels join a link group and follow that group's instrument. The information
 * cutoff and availability mode are desk-wide, because they decide which evidence
 * is allowed to exist at all — a panel cannot opt out of point-in-time truth.
 * Pure reducer so propagation, resets and missing identities are testable.
 */

import type { AsOfMode } from '../types'

export const LINK_GROUPS = ['A', 'B', 'C', 'D'] as const
export type LinkGroup = (typeof LINK_GROUPS)[number]

export interface GroupSelection {
  issuerId: string | null
  securityId: string | null
}

export interface LinkState {
  activeGroup: LinkGroup
  groups: Record<LinkGroup, GroupSelection>
  asOf: string | null
  mode: AsOfMode
}

export type LinkAction =
  | { type: 'select'; group: LinkGroup; issuerId: string | null; securityId: string | null }
  | { type: 'group'; group: LinkGroup }
  | { type: 'asof'; asOf: string | null }
  | { type: 'mode'; mode: AsOfMode }
  | { type: 'reset' }

export function emptyGroups(): Record<LinkGroup, GroupSelection> {
  return {
    A: { issuerId: null, securityId: null },
    B: { issuerId: null, securityId: null },
    C: { issuerId: null, securityId: null },
    D: { issuerId: null, securityId: null },
  }
}

export function initialLinkState(): LinkState {
  return { activeGroup: 'A', groups: emptyGroups(), asOf: null, mode: 'public_available' }
}

export function linkReducer(state: LinkState, action: LinkAction): LinkState {
  switch (action.type) {
    case 'select': {
      const next = { issuerId: action.issuerId, securityId: action.securityId }
      return { ...state, groups: { ...state.groups, [action.group]: next } }
    }
    case 'group':
      return { ...state, activeGroup: action.group }
    case 'asof':
      return { ...state, asOf: action.asOf }
    case 'mode':
      return { ...state, mode: action.mode }
    case 'reset':
      return initialLinkState()
    default:
      return state
  }
}

/** The selection a panel follows. Panels without a group follow the active group. */
export function resolveInstrument(state: LinkState, group: LinkGroup | null | undefined): GroupSelection {
  return state.groups[group ?? state.activeGroup]
}

/** Panels that cannot show anything yet say which input they are waiting for. */
export function missingLink(state: LinkState, group: LinkGroup | null | undefined): string | null {
  const selection = resolveInstrument(state, group)
  if (!selection.issuerId) return 'No instrument selected in this link group.'
  return null
}

export function isValidAsOf(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

export function cutoffLabel(state: LinkState): string {
  return state.asOf ?? 'latest available'
}

export function linkSummary(state: LinkState): string {
  const selection = resolveInstrument(state, state.activeGroup)
  const instrument = selection.issuerId ?? 'no instrument'
  return `Group ${state.activeGroup} · ${instrument} · ${cutoffLabel(state)} · ${state.mode === 'public_available' ? 'public availability' : 'ingested availability'}`
}
