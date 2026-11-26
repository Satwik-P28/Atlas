import { describe, expect, it } from 'vitest'
import {
  cutoffLabel,
  initialLinkState,
  isValidAsOf,
  linkReducer,
  linkSummary,
  missingLink,
  resolveInstrument,
  type LinkState,
} from './links'

describe('link groups', () => {
  it('keeps group selections independent', () => {
    let state: LinkState = initialLinkState()
    state = linkReducer(state, { type: 'select', group: 'A', issuerId: 'ISS-JPM', securityId: 'SEC-JPM' })
    state = linkReducer(state, { type: 'select', group: 'B', issuerId: 'ISS-AAPL', securityId: 'SEC-AAPL' })
    expect(resolveInstrument(state, 'A')).toEqual({ issuerId: 'ISS-JPM', securityId: 'SEC-JPM' })
    expect(resolveInstrument(state, 'B')).toEqual({ issuerId: 'ISS-AAPL', securityId: 'SEC-AAPL' })
    expect(resolveInstrument(state, 'C')).toEqual({ issuerId: null, securityId: null })
  })

  it('lets an ungrouped panel follow the active group', () => {
    let state = linkReducer(initialLinkState(), { type: 'select', group: 'B', issuerId: 'ISS-AAPL', securityId: 'SEC-AAPL' })
    state = linkReducer(state, { type: 'group', group: 'B' })
    expect(resolveInstrument(state, null)).toEqual({ issuerId: 'ISS-AAPL', securityId: 'SEC-AAPL' })
  })

  it('reports a missing instrument instead of rendering empty data', () => {
    const state = initialLinkState()
    expect(missingLink(state, 'A')).toMatch(/No instrument selected/)
    const selected = linkReducer(state, { type: 'select', group: 'A', issuerId: 'ISS-JPM', securityId: null })
    expect(missingLink(selected, 'A')).toBeNull()
  })

  it('keeps the cutoff and availability mode desk-wide', () => {
    let state = linkReducer(initialLinkState(), { type: 'asof', asOf: '2024-06-01' })
    state = linkReducer(state, { type: 'mode', mode: 'atlas_ingested' })
    state = linkReducer(state, { type: 'select', group: 'A', issuerId: 'ISS-AAPL', securityId: 'SEC-AAPL' })
    expect(state.asOf).toBe('2024-06-01')
    expect(state.mode).toBe('atlas_ingested')
    expect(cutoffLabel(state)).toBe('2024-06-01')
    expect(linkSummary(state)).toContain('ingested availability')
  })

  it('resets every group, the cutoff and the mode', () => {
    let state = linkReducer(initialLinkState(), { type: 'select', group: 'A', issuerId: 'ISS-JPM', securityId: 'SEC-JPM' })
    state = linkReducer(state, { type: 'asof', asOf: '2024-06-01' })
    state = linkReducer(state, { type: 'reset' })
    expect(state).toEqual(initialLinkState())
  })

  it('validates cutoff dates', () => {
    expect(isValidAsOf('2024-02-29')).toBe(true)
    expect(isValidAsOf('2023-02-29')).toBe(false)
    expect(isValidAsOf('yesterday')).toBe(false)
  })

  it('labels the default cutoff as latest available', () => {
    expect(cutoffLabel(initialLinkState())).toBe('latest available')
  })
})
