/** Formatting is presentation only: it never rescales a number's meaning.
 * Units come from the API, so `fraction` renders as a percentage and `ratio` as a
 * multiple — the UI does not guess. */

export function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`
  return `${sign}$${abs.toFixed(2)}`
}

export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

export function fmtUnit(value: string | number | null | undefined, unit: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = typeof value === 'number' ? value : Number(value)
  if (unit === null || unit === undefined) return Number.isNaN(numeric) ? String(value) : fmtNumber(numeric)
  if (Number.isNaN(numeric)) return String(value)
  if (unit === 'USD') return fmtCompact(numeric)
  if (unit === 'USD/share') return `$${numeric.toFixed(2)}`
  if (unit === 'shares') return `${(numeric / 1e6).toFixed(1)}M`
  if (unit === 'fraction') return fmtPct(numeric)
  if (unit === 'ratio') return `${numeric.toFixed(2)}×`
  if (unit === 'pure') return numeric.toFixed(2)
  if (unit === 'days') return `${numeric.toFixed(0)}d`
  return `${fmtNumber(numeric)} ${unit}`
}

export function fmtSignedPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const pct = value * 100
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return '—'
  return value.slice(0, 10)
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  })
}

export function fiscalLabel(fiscalYear: number | null, fiscalPeriod: string | null): string {
  if (!fiscalYear) return fiscalPeriod ?? ''
  return `FY${fiscalYear}${fiscalPeriod && fiscalPeriod !== 'FY' ? ` ${fiscalPeriod}` : ''}`
}

export function toneForNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value) || value === 0) return 'neutral'
  return value > 0 ? 'positive' : 'negative'
}

export function truncate(value: string, max = 60): string {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`
}
