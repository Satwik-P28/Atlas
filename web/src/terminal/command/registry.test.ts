import { describe, expect, it } from 'vitest'
import { completeCommands, isIsoDate, parseCommand, type CommandContext } from './registry'

const context: CommandContext = {
  instruments: [
    { issuer_id: 'ISS-JPM', legal_name: 'JPMorgan Chase & Co.', tickers: ['JPM'] },
    { issuer_id: 'ISS-AAPL', legal_name: 'Apple Inc.', tickers: ['AAPL'] },
    { issuer_id: 'ISS-BAC', legal_name: 'Bank of America Corporation', tickers: ['BAC'] },
    { issuer_id: 'ISS-BK', legal_name: 'Bank of New York Mellon', tickers: ['BK'] },
  ],
  workspaces: [
    { workspace_id: 'ws-1', name: 'Desk A' },
    { workspace_id: 'ws-2', name: 'Desk B' },
  ],
}

describe('instrument commands', () => {
  it('selects an instrument by ticker', () => {
    const result = parseCommand('AAPL', context)
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.command).toMatchObject({ id: 'instrument', issuerId: 'ISS-AAPL', panel: null })
  })

  it('selects an instrument and a panel, case-insensitively', () => {
    const result = parseCommand('jpm fin', context)
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.command).toMatchObject({ id: 'instrument', issuerId: 'ISS-JPM', panel: 'statements' })
  })

  it('maps topics to the panels that exist', () => {
    const map: Record<string, string> = {
      'AAPL VAL': 'metrics',
      'AAPL CHART': 'chart',
      'AAPL EVIDENCE': 'evidence',
      'AAPL MEMO': 'memo',
      'AAPL MODEL': 'model',
      'AAPL DIAG': 'diagnostics',
    }
    for (const [input, panel] of Object.entries(map)) {
      const result = parseCommand(input, context)
      expect(result.ok).toBe(true)
      if (result.ok) expect(result.command).toMatchObject({ panel })
    }
  })

  it('refuses an unknown symbol without inventing one', () => {
    const result = parseCommand('ZZZZ', context)
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.error.code).toBe('unknown_instrument')
  })

  it('refuses ambiguous name prefixes with candidates', () => {
    const result = parseCommand('BANK', context)
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.error.code).toBe('ambiguous_instrument')
    expect(result.error.candidates?.length).toBeGreaterThan(1)
  })

  it('refuses an unknown topic', () => {
    const result = parseCommand('AAPL PIZZA', context)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error.code).toBe('unknown_topic')
  })

  it('refuses an empty command', () => {
    expect(parseCommand('   ', context).ok).toBe(false)
  })
})

describe('desk commands', () => {
  it('accepts an ISO cutoff and rejects an impossible date', () => {
    const ok = parseCommand('SET ASOF 2024-06-01', context)
    expect(ok.ok).toBe(true)
    if (ok.ok) expect(ok.command).toMatchObject({ id: 'asof', asOf: '2024-06-01' })
    const bad = parseCommand('SET ASOF 2024-13-01', context)
    expect(bad.ok).toBe(false)
    if (!bad.ok) expect(bad.error.code).toBe('invalid_date')
    const cleared = parseCommand('SET ASOF CLEAR', context)
    expect(cleared.ok).toBe(true)
    if (cleared.ok) expect(cleared.command).toMatchObject({ id: 'asof', asOf: null })
  })

  it('validates the availability mode', () => {
    const ok = parseCommand('SET MODE atlas_ingested', context)
    expect(ok.ok).toBe(true)
    if (ok.ok) expect(ok.command).toMatchObject({ id: 'mode', mode: 'atlas_ingested' })
    expect(parseCommand('SET MODE backfilled', context).ok).toBe(false)
  })

  it('opens a saved workspace by name', () => {
    const result = parseCommand('WORKSPACE Desk B', context)
    expect(result.ok).toBe(true)
    if (result.ok) expect(result.command).toMatchObject({ id: 'workspace', workspaceId: 'ws-2' })
    expect(parseCommand('WORKSPACE Missing', context).ok).toBe(false)
  })

  it('exposes save, reset, diagnostics and help', () => {
    expect(parseCommand('SAVE WORKSPACE', context)).toMatchObject({ ok: true })
    expect(parseCommand('RESET LAYOUT', context)).toMatchObject({ ok: true })
    expect(parseCommand('SHOW DIAGNOSTICS', context)).toMatchObject({ ok: true })
    expect(parseCommand('?', context)).toMatchObject({ ok: true })
  })

  it('validates ISO dates strictly', () => {
    expect(isIsoDate('2024-02-29')).toBe(true)
    expect(isIsoDate('2023-02-29')).toBe(false)
    expect(isIsoDate('2024-2-9')).toBe(false)
  })
})

describe('completions', () => {
  it('suggests instruments by ticker prefix', () => {
    const suggestions = completeCommands('AA', context)
    expect(suggestions.some((entry) => entry.value === 'AAPL' && entry.kind === 'instrument')).toBe(true)
  })

  it('suggests topics after a symbol', () => {
    const suggestions = completeCommands('AAPL ', context)
    expect(suggestions.map((entry) => entry.value)).toContain('AAPL FIN')
    expect(suggestions.every((entry) => entry.kind === 'topic')).toBe(true)
  })

  it('never offers an instrument Atlas does not cover', () => {
    const suggestions = completeCommands('ZZZ', context)
    expect(suggestions.some((entry) => entry.kind === 'instrument')).toBe(false)
  })
})
