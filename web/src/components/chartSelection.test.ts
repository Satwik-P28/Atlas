import { describe, expect, it } from 'vitest'
import {
  indexFromLogical,
  keyboardSelection,
  orderedRange,
  rangeForSessions,
  selectionStillValid,
  sessionsForRange,
} from './chartSelection'

const DATES = ['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07', '2025-01-08']

describe('chart selection mapping', () => {
  it('snaps fractional logical coordinates to real bars and clamps to the data', () => {
    expect(indexFromLogical(2.4, DATES.length)).toBe(2)
    expect(indexFromLogical(2.6, DATES.length)).toBe(3)
    expect(indexFromLogical(-3, DATES.length)).toBe(0)
    expect(indexFromLogical(99, DATES.length)).toBe(4)
    expect(indexFromLogical(null, DATES.length)).toBeNull()
    expect(indexFromLogical(1, 0)).toBeNull()
  })

  it('normalises a reversed drag instead of producing an inverted range', () => {
    expect(orderedRange(3, 1, DATES.length)).toEqual({ from: 1, to: 3 })
    expect(orderedRange(1, 3, DATES.length)).toEqual({ from: 1, to: 3 })
    expect(orderedRange(0, 0, DATES.length)).toEqual({ from: 0, to: 0 })
    expect(orderedRange(0, 4, 0)).toBeNull()
  })

  it('resolves a range to the stored sessions it covers, including one candle', () => {
    expect(sessionsForRange(DATES, { from: 1, to: 3 })).toEqual({
      start: '2025-01-03',
      end: '2025-01-07',
    })
    expect(sessionsForRange(DATES, { from: 2, to: 2 })).toEqual({
      start: '2025-01-06',
      end: '2025-01-06',
    })
    expect(sessionsForRange(DATES, { from: 0, to: 9 })).toBeNull()
  })

  it('rejects a selection that no longer exists after a timeframe change', () => {
    const weekly = ['2025-01-03', '2025-01-10']
    const selection = { start: '2025-01-02', end: '2025-01-07' }
    expect(selectionStillValid(DATES, selection)).toBe(true)
    expect(selectionStillValid(weekly, selection)).toBe(false)
    expect(rangeForSessions(weekly, selection)).toBeNull()
  })

  it('supports keyboard extension and escape-style reset', () => {
    const selection = { start: '2025-01-03', end: '2025-01-06' }
    expect(rangeForSessions(DATES, selection)).toEqual({ from: 1, to: 2 })
    expect(keyboardSelection(DATES, selection, 'ArrowRight', true)).toEqual({ from: 1, to: 3 })
    expect(keyboardSelection(DATES, selection, 'ArrowRight', false)).toEqual({ from: 3, to: 3 })
    expect(keyboardSelection(DATES, selection, 'Home', true)).toEqual({ from: 0, to: 1 })
    expect(keyboardSelection(DATES, null, 'ArrowLeft', false)).toEqual({ from: 0, to: 0 })
  })
})
