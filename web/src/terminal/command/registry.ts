/** Command grammar for the Advanced workstation.
 *
 * Commands are parsed here and then executed by a registry of real actions: a
 * command never runs a shell, and it never invents an instrument. An unresolved
 * symbol is an error with candidates, not a demo page.
 */

export interface CommandInstrument {
  issuer_id: string
  legal_name: string
  tickers: string[]
}

export interface CommandWorkspace {
  workspace_id: string
  name: string
}

export interface CommandContext {
  instruments: CommandInstrument[]
  workspaces: CommandWorkspace[]
}

export type PanelKind =
  | 'monitor'
  | 'chart'
  | 'statements'
  | 'metrics'
  | 'evidence'
  | 'memo'
  | 'model'
  | 'diagnostics'

export type AtlasCommand =
  | { id: 'instrument'; label: string; issuerId: string; panel: PanelKind | null }
  | { id: 'asof'; label: string; asOf: string | null }
  | { id: 'mode'; label: string; mode: 'public_available' | 'atlas_ingested' }
  | { id: 'workspace'; label: string; workspaceId: string }
  | { id: 'panel'; label: string; panel: PanelKind }
  | { id: 'save'; label: string }
  | { id: 'reset'; label: string }
  | { id: 'help'; label: string }

export interface CommandError {
  code: string
  message: string
  hint?: string
  candidates?: string[]
}

export type ParseResult = { ok: true; command: AtlasCommand } | { ok: false; error: CommandError }

const TOPICS: Record<string, PanelKind> = {
  FIN: 'statements',
  FINANCIALS: 'statements',
  STATEMENTS: 'statements',
  VAL: 'metrics',
  VALUATION: 'metrics',
  METRICS: 'metrics',
  CHART: 'chart',
  PRICE: 'chart',
  EVIDENCE: 'evidence',
  EV: 'evidence',
  MEMO: 'memo',
  CLAIMS: 'memo',
  MODEL: 'model',
  MODELS: 'model',
  MONITOR: 'monitor',
  DIAG: 'diagnostics',
  DIAGNOSTICS: 'diagnostics',
}

export const TOPIC_HELP: Array<{ topic: string; panel: PanelKind; description: string }> = [
  { topic: 'FIN', panel: 'statements', description: 'Point-in-time financial statements' },
  { topic: 'VAL', panel: 'metrics', description: 'Valuation and profitability metrics' },
  { topic: 'CHART', panel: 'chart', description: 'Price chart with the active cutoff' },
  { topic: 'EVIDENCE', panel: 'evidence', description: 'Evidence inspector for the selected record' },
  { topic: 'MEMO', panel: 'memo', description: 'Research memo and claim register' },
  { topic: 'MODEL', panel: 'model', description: 'Model version, inputs and diagnostics' },
  { topic: 'MONITOR', panel: 'monitor', description: 'Universe monitor with latest observed prices' },
  { topic: 'DIAG', panel: 'diagnostics', description: 'Runtime, schema and reproduction metadata' },
]

export const COMMAND_HELP: Array<{ command: string; description: string }> = [
  { command: 'AAPL', description: 'Select an instrument by ticker, CIK or name' },
  { command: 'JPM FIN', description: 'Select JPM and open its statements panel' },
  { command: 'AAPL EVIDENCE', description: 'Open the evidence inspector for AAPL' },
  { command: 'SET ASOF 2024-06-01', description: 'Move the information cutoff' },
  { command: 'SET MODE public_available', description: 'Choose point-in-time availability semantics' },
  { command: 'WORKSPACE <name>', description: 'Open a saved workstation layout' },
  { command: 'SHOW DIAGNOSTICS', description: 'Open the diagnostics panel' },
  { command: 'SAVE WORKSPACE', description: 'Save the current layout' },
  { command: 'RESET LAYOUT', description: 'Restore the default desk' },
]

const DATE = /^\d{4}-\d{2}-\d{2}$/

function error(code: string, message: string, hint?: string, candidates?: string[]): ParseResult {
  return { ok: false, error: { code, message, hint, candidates } }
}

export function isIsoDate(value: string): boolean {
  if (!DATE.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function resolveInstrument(token: string, context: CommandContext): ParseResult | { instrument: CommandInstrument } {
  const needle = token.trim().toLowerCase()
  if (!needle) return { ok: false, error: { code: 'missing_instrument', message: 'Name an instrument first.' } }
  const tickerMatches = context.instruments.filter((item) =>
    item.tickers.some((ticker) => ticker.toLowerCase() === needle),
  )
  const idMatches = context.instruments.filter((item) => item.issuer_id.toLowerCase() === needle)
  const nameMatches = needle.length >= 3
    ? context.instruments.filter((item) => item.legal_name.toLowerCase().startsWith(needle))
    : []
  const matches = [...idMatches, ...tickerMatches, ...nameMatches].filter(
    (item, index, all) => all.findIndex((other) => other.issuer_id === item.issuer_id) === index,
  )
  if (matches.length === 1) return { instrument: matches[0] }
  if (matches.length > 1) {
    return error(
      'ambiguous_instrument',
      `“${token}” matches ${matches.length} instruments.`,
      'Type a ticker to disambiguate.',
      matches.slice(0, 6).map((item) => item.tickers[0] ?? item.legal_name),
    )
  }
  const suggestions = context.instruments
    .filter((item) => item.tickers.some((ticker) => ticker.toLowerCase().startsWith(needle.slice(0, 2))))
    .slice(0, 6)
    .map((item) => item.tickers[0] ?? item.legal_name)
  return error(
    'unknown_instrument',
    `Atlas has no instrument “${token}”.`,
    'Atlas does not invent a security; pick one of the covered instruments.',
    suggestions,
  )
}

export function parseCommand(input: string, context: CommandContext): ParseResult {
  const raw = input.trim().replace(/\s+/g, ' ')
  if (!raw) return error('empty', 'Type a command.')
  const upper = raw.toUpperCase()

  if (upper === 'HELP' || upper === '?') return { ok: true, command: { id: 'help', label: 'Help' } }
  if (upper === 'SAVE WORKSPACE' || upper === 'SAVE') {
    return { ok: true, command: { id: 'save', label: 'Save workspace' } }
  }
  if (upper === 'RESET LAYOUT' || upper === 'RESET') {
    return { ok: true, command: { id: 'reset', label: 'Reset layout' } }
  }
  if (upper === 'SHOW DIAGNOSTICS' || upper === 'DIAGNOSTICS') {
    return { ok: true, command: { id: 'panel', label: 'Diagnostics', panel: 'diagnostics' } }
  }
  if (upper === 'OPEN MODEL' || upper === 'MODEL') {
    return { ok: true, command: { id: 'panel', label: 'Model inspector', panel: 'model' } }
  }
  if (upper === 'OPEN CLAIMS' || upper === 'SHOW CLAIMS') {
    return { ok: true, command: { id: 'panel', label: 'Claims', panel: 'memo' } }
  }

  if (upper.startsWith('SET ASOF')) {
    const value = raw.split(/ +/)[2] ?? ''
    if (value.toUpperCase() === 'CLEAR' || value === '') {
      return { ok: true, command: { id: 'asof', label: 'Cutoff cleared', asOf: null } }
    }
    if (!isIsoDate(value)) {
      return error('invalid_date', `“${value}” is not an ISO date.`, 'Use SET ASOF YYYY-MM-DD.')
    }
    return { ok: true, command: { id: 'asof', label: `Cutoff ${value}`, asOf: value } }
  }

  if (upper.startsWith('SET MODE')) {
    const value = (raw.split(/ +/)[2] ?? '').toLowerCase()
    if (value !== 'public_available' && value !== 'atlas_ingested') {
      return error(
        'invalid_mode',
        `Unknown availability mode “${value || ''}”.`,
        'Use SET MODE public_available or SET MODE atlas_ingested.',
        ['public_available', 'atlas_ingested'],
      )
    }
    return { ok: true, command: { id: 'mode', label: `Mode ${value}`, mode: value } }
  }

  if (upper.startsWith('WORKSPACE ')) {
    const wanted = raw.slice('WORKSPACE '.length).trim()
    const needle = wanted.toLowerCase()
    const matches = context.workspaces.filter(
      (workspace) =>
        workspace.name.toLowerCase() === needle ||
        workspace.workspace_id.toLowerCase() === needle ||
        workspace.name.toLowerCase().startsWith(needle),
    )
    if (matches.length === 1) {
      return {
        ok: true,
        command: { id: 'workspace', label: `Workspace ${matches[0].name}`, workspaceId: matches[0].workspace_id },
      }
    }
    if (matches.length > 1) {
      return error(
        'ambiguous_workspace',
        `“${wanted}” matches ${matches.length} workspaces.`,
        'Use the full workspace name.',
        matches.slice(0, 5).map((workspace) => workspace.name),
      )
    }
    return error(
      'unknown_workspace',
      `No saved workspace named “${wanted}”.`,
      'Create one with SAVE WORKSPACE first.',
      context.workspaces.slice(0, 5).map((workspace) => workspace.name),
    )
  }

  const tokens = raw.split(' ')
  const resolved = resolveInstrument(tokens[0], context)
  if ('ok' in resolved) return resolved
  if (tokens.length === 1) {
    return {
      ok: true,
      command: {
        id: 'instrument',
        label: resolved.instrument.tickers[0] ?? resolved.instrument.legal_name,
        issuerId: resolved.instrument.issuer_id,
        panel: null,
      },
    }
  }
  const topic = tokens[1].toUpperCase()
  const panel = TOPICS[topic]
  if (!panel) {
    return error(
      'unknown_topic',
      `“${tokens[1]}” is not an Atlas panel.`,
      'Try FIN, VAL, CHART, EVIDENCE, MEMO, MODEL, MONITOR or DIAG.',
      TOPIC_HELP.map((entry) => entry.topic),
    )
  }
  return {
    ok: true,
    command: {
      id: 'instrument',
      label: `${resolved.instrument.tickers[0] ?? resolved.instrument.legal_name} ${topic}`,
      issuerId: resolved.instrument.issuer_id,
      panel,
    },
  }
}

export interface Completion {
  value: string
  label: string
  description: string
  kind: 'command' | 'instrument' | 'topic' | 'workspace'
}

/** Suggestions for the palette: verbs, instruments, topics and workspaces. */
export function completeCommands(prefix: string, context: CommandContext, limit = 9): Completion[] {
  // Keep a trailing space: "AAPL " means "topics for AAPL", not "symbol AAPL".
  const raw = prefix.replace(/^\s+/, '')
  const upper = raw.toUpperCase()
  const parts = raw.split(/\s+/)
  const items: Completion[] = []

  if (parts.length === 1 && !/\s$/.test(raw)) {
    const needle = (parts[0] ?? '').toLowerCase()
    for (const instrument of context.instruments) {
      const ticker = instrument.tickers[0] ?? ''
      if (!needle || ticker.toLowerCase().startsWith(needle) || instrument.legal_name.toLowerCase().startsWith(needle)) {
        items.push({
          value: ticker || instrument.legal_name,
          label: `${ticker} · ${instrument.legal_name}`,
          description: 'Instrument',
          kind: 'instrument',
        })
      }
    }
    for (const entry of COMMAND_HELP) {
      if (!needle || entry.command.toLowerCase().startsWith(needle)) {
        items.push({ value: entry.command, label: entry.command, description: entry.description, kind: 'command' })
      }
    }
    for (const workspace of context.workspaces) {
      if (needle && workspace.name.toLowerCase().startsWith(needle)) {
        items.push({
          value: `WORKSPACE ${workspace.name}`,
          label: `WORKSPACE ${workspace.name}`,
          description: 'Saved layout',
          kind: 'workspace',
        })
      }
    }
    return items.slice(0, limit)
  }

  const first = parts[0]
  if (upper.startsWith('SET ASOF')) {
    return [{ value: 'SET ASOF ', label: 'SET ASOF YYYY-MM-DD', description: 'Information cutoff', kind: 'command' }]
  }
  if (upper.startsWith('SET MODE')) {
    return ['public_available', 'atlas_ingested'].map((mode) => ({
      value: `SET MODE ${mode}`,
      label: `SET MODE ${mode}`,
      description: mode === 'public_available' ? 'Exact or date-precise public availability' : 'When Atlas ingested the evidence',
      kind: 'command' as const,
    }))
  }
  if (upper.startsWith('WORKSPACE')) {
    return context.workspaces
      .filter((workspace) => workspace.name.toLowerCase().includes(raw.slice('WORKSPACE '.length).toLowerCase()))
      .slice(0, limit)
      .map((workspace) => ({
        value: `WORKSPACE ${workspace.name}`,
        label: `WORKSPACE ${workspace.name}`,
        description: 'Saved layout',
        kind: 'workspace' as const,
      }))
  }
  const partial = (parts[1] ?? '').toUpperCase()
  return TOPIC_HELP.filter((entry) => entry.topic.startsWith(partial))
    .slice(0, limit)
    .map((entry) => ({
      value: `${first} ${entry.topic}`,
      label: `${first.toUpperCase()} ${entry.topic}`,
      description: entry.description,
      kind: 'topic' as const,
    }))
}
