import type { CommandIndexEntry, CommandIndexPayload } from '../../api'

/** Every palette result performs a real action: a route that exists, or a question
 * that the answer resolver will answer or refuse. There is no "coming soon" entry. */
export type PaletteAction =
  | { kind: 'navigate'; path: string }
  | { kind: 'question'; issuer_id: string; concept: string; period: string }
  | { kind: 'concept'; concept: string; statement: string }
  | { kind: 'model'; model: string }
  | { kind: 'strategy'; object_id: string }

export interface PaletteEntity {
  id: string
  label: string
  description: string
  category: string
  action: PaletteAction
  metadata?: Record<string, unknown>
}

export const CATEGORY_LABELS: Record<string, string> = {
  companies: 'Company',
  concepts: 'Concept',
  filings: 'Filing',
  questions: 'Question',
  models: 'Model',
  strategies: 'Strategy',
  research: 'Saved research',
  experiments: 'Experiment',
  workspaces: 'Workspace',
  packages: 'Package',
}

export const RECENTS_KEY = 'atlas.palette.recents'
const RECENTS_LIMIT = 8

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category
}

function toEntity(entry: CommandIndexEntry): PaletteEntity {
  return {
    id: entry.id,
    label: entry.label,
    description: entry.description,
    category: entry.category,
    action: entry.action as PaletteAction,
    metadata: entry.metadata,
  }
}

export function fromIndexEntry(entry: CommandIndexEntry): PaletteEntity {
  return toEntity(entry)
}

/** Flatten the index once. Rendering order is stable so keyboard selection is stable. */
export function flattenIndex(index: CommandIndexPayload | null): PaletteEntity[] {
  if (!index) return []
  const order = Object.keys(CATEGORY_LABELS)
  const categories = [
    ...order.filter((name) => name in index.categories),
    ...Object.keys(index.categories).filter((name) => !order.includes(name)),
  ]
  return categories.flatMap((name) => (index.categories[name] ?? []).map(toEntity))
}

function score(entity: PaletteEntity, tokens: string[]): number {
  if (!tokens.length) return 0
  const label = entity.label.toLowerCase()
  const description = entity.description.toLowerCase()
  const category = entity.category.toLowerCase()
  let total = 0
  for (const token of tokens) {
    if (label === token) total += 120
    else if (label.startsWith(token)) total += 90
    else if (label.split(/[\s·/]+/).some((word) => word.startsWith(token))) total += 70
    else if (label.includes(token)) total += 45
    else if (description.includes(token)) total += 20
    else if (category.includes(token)) total += 10
    else return 0
  }
  return total
}

/** Search the index. An empty query returns nothing: recents are a separate row set. */
export function searchEntities(
  index: CommandIndexPayload | null,
  query: string,
  limit = 10,
): PaletteEntity[] {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!tokens.length) return []
  return flattenIndex(index)
    .map((entity) => ({ entity, value: score(entity, tokens) }))
    .filter((row) => row.value > 0)
    .sort((left, right) => right.value - left.value || left.entity.label.localeCompare(right.entity.label))
    .slice(0, limit)
    .map((row) => row.entity)
}

/** The route or action a palette entry resolves to. Only in-app paths are accepted. */
export function actionPath(action: PaletteAction): string | null {
  switch (action.kind) {
    case 'navigate':
      return action.path.startsWith('/') ? action.path : null
    case 'question':
      return `/answers?issuer=${encodeURIComponent(action.issuer_id)}&concept=${encodeURIComponent(
        action.concept,
      )}&period=${encodeURIComponent(action.period)}`
    case 'concept':
      return `/answers?concept=${encodeURIComponent(action.concept)}`
    case 'model':
      return `/studio?model=${encodeURIComponent(action.model)}`
    case 'strategy':
      return `/lab?object=${encodeURIComponent(action.object_id)}`
    default:
      return null
  }
}

// Some browsers (and some jsdom configurations) expose no usable localStorage: a
// private window throws on write and an opaque origin may not define it at all. Recent
// activity is a convenience, so it degrades to an in-memory list instead of failing.
const memory = new Map<string, string>()

function storage(): Pick<Storage, 'getItem' | 'setItem'> {
  try {
    const local = window.localStorage
    if (local) return local
  } catch {
    /* fall through to memory */
  }
  return {
    getItem: (key: string) => memory.get(key) ?? null,
    setItem: (key: string, value: string) => {
      memory.set(key, value)
    },
  }
}

export function clearRecents(): void {
  memory.delete(RECENTS_KEY)
  try {
    window.localStorage?.removeItem(RECENTS_KEY)
  } catch {
    /* nothing to clear */
  }
}

export function loadRecents(): PaletteEntity[] {
  try {
    const raw = storage().getItem(RECENTS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (item): item is PaletteEntity =>
        Boolean(item) && typeof item.id === 'string' && typeof item.label === 'string' &&
        typeof item.category === 'string' && Boolean(item.action),
    )
  } catch {
    return []
  }
}

/** Recent activity is bounded and de-duplicated by category+id: a launcher, not a log. */
export function recordRecent(entity: PaletteEntity): PaletteEntity[] {
  const next = [entity, ...loadRecents().filter(
    (item) => !(item.category === entity.category && item.id === entity.id),
  )].slice(0, RECENTS_LIMIT)
  try {
    storage().setItem(RECENTS_KEY, JSON.stringify(next))
  } catch {
    /* storage unavailable: recents are a convenience, never the source of a result */
  }
  return next
}
