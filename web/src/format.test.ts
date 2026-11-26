import { describe, expect, it } from 'vitest'
import { fiscalLabel, fmtCompact, fmtDate, fmtPct, fmtSignedPct, fmtUnit } from './format'

describe('financial formatting', () => {
  it('compacts magnitudes without changing their scale', () => {
    expect(fmtCompact(383_285_000_000)).toBe('$383.29B')
    expect(fmtCompact(1_500_000_000_000)).toBe('$1.50T')
    expect(fmtCompact(-2_500_000)).toBe('-$2.50M')
    expect(fmtCompact(null)).toBe('—')
  })

  it('renders fractions as percentages, never as raw decimals', () => {
    expect(fmtUnit(0.269, 'fraction')).toBe('26.90%')
    expect(fmtUnit(0.269, 'ratio')).toBe('0.27×')
    expect(fmtPct(0.0123)).toBe('1.23%')
    expect(fmtSignedPct(-0.041)).toBe('-4.10%')
    expect(fmtSignedPct(0.041)).toBe('+4.10%')
  })

  it('uses units from the API rather than guessing', () => {
    expect(fmtUnit('416161000000', 'USD')).toBe('$416.16B')
    expect(fmtUnit('6.13', 'USD/share')).toBe('$6.13')
    expect(fmtUnit('15400000000', 'shares')).toBe('15400.0M')
    expect(fmtUnit('12', 'pure')).toBe('12.00')
    expect(fmtUnit(null, 'USD')).toBe('—')
  })

  it('formats dates as calendar dates and fiscal labels explicitly', () => {
    expect(fmtDate('2025-09-27T00:00:00Z')).toBe('2025-09-27')
    expect(fmtDate(null)).toBe('—')
    expect(fiscalLabel(2025, 'FY')).toBe('FY2025')
    expect(fiscalLabel(2024, 'Q1')).toBe('FY2024 Q1')
    expect(fiscalLabel(null, 'FY')).toBe('FY')
  })
})
