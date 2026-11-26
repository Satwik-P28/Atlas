/** Pure helpers for mapping a chart drag onto actual stored sessions.
 *
 * Lightweight Charts exposes `timeScale().coordinateToLogical(x)` and
 * `logicalToCoordinate(index)`. Those are supported public APIs, but they return
 * fractional logical indices, `null` outside the data, and the drag can run in either
 * direction. All of that is decided here so the component only draws.
 */

export interface SessionSelection {
  start: string
  end: string
}

export interface IndexRange {
  from: number
  to: number
}

/** Snap a fractional logical coordinate to the nearest existing bar index. */
export function indexFromLogical(logical: number | null, count: number): number | null {
  if (logical === null || !Number.isFinite(logical) || count < 1) return null
  const rounded = Math.round(logical)
  if (rounded < 0) return 0
  if (rounded > count - 1) return count - 1
  return rounded
}

/** Order two bar indices regardless of drag direction. */
export function orderedRange(a: number, b: number, count: number): IndexRange | null {
  if (count < 1) return null
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  const left = Math.max(0, Math.min(count - 1, Math.round(a)))
  const right = Math.max(0, Math.min(count - 1, Math.round(b)))
  return left <= right ? { from: left, to: right } : { from: right, to: left }
}

/** The session dates a selection resolves to, or null when it resolves to nothing. */
export function sessionsForRange(
  dates: readonly string[],
  range: IndexRange | null,
): SessionSelection | null {
  if (!range || dates.length === 0) return null
  if (range.from < 0 || range.to >= dates.length) return null
  const start = dates[range.from]
  const end = dates[range.to]
  if (!start || !end) return null
  return { start, end }
}

/** Bounds of a previously selected pair of dates inside the current series. */
export function rangeForSessions(
  dates: readonly string[],
  selection: SessionSelection | null,
): IndexRange | null {
  if (!selection || dates.length === 0) return null
  const first = dates.indexOf(selection.start)
  const last = dates.indexOf(selection.end)
  if (first < 0 || last < 0) return null
  return orderedRange(first, last, dates.length)
}

/** Whether a security/timeframe change invalidates a stored selection. */
export function selectionStillValid(
  dates: readonly string[],
  selection: SessionSelection | null,
): selection is SessionSelection {
  return rangeForSessions(dates, selection) !== null
}

/** Arrow-key motion: a single cursor, or a range that grows from its anchor. */
export function keyboardSelection(
  dates: readonly string[],
  selection: SessionSelection | null,
  key: 'ArrowLeft' | 'ArrowRight' | 'Home' | 'End',
  extend: boolean,
): IndexRange | null {
  if (dates.length === 0) return null
  const current = rangeForSessions(dates, selection) ?? { from: 0, to: 0 }
  if (!selection) {
    return key === 'End' ? { from: dates.length - 1, to: dates.length - 1 } : current
  }
  const step = key === 'ArrowLeft' ? -1 : key === 'ArrowRight' ? 1 : 0
  const target =
    key === 'Home' ? 0 : key === 'End' ? dates.length - 1 : current.to + step
  const clamped = Math.max(0, Math.min(dates.length - 1, target))
  return extend
    ? orderedRange(current.from, clamped, dates.length)
    : { from: clamped, to: clamped }
}
