import { beforeEach, describe, expect, it } from 'vitest'
import type { CommandIndexPayload } from '../../api'
import {
  actionPath,
  clearRecents,
  flattenIndex,
  loadRecents,
  recordRecent,
  searchEntities,
  RECENTS_KEY,
  type PaletteEntity,
} from './indexSearch'

function entity(overrides: Partial<PaletteEntity> = {}): PaletteEntity {
  return {
    id: 'ISS-1',
    label: 'AAPL · Apple Inc.',
    description: 'Apple Inc.',
    category: 'companies',
    action: { kind: 'navigate', path: '/companies/ISS-1' },
    ...overrides,
  }
}

function payload(): CommandIndexPayload {
  return {
    schema: 'atlas.command_index.v1',
    generated_at: '2024-01-01T00:00:00Z',
    policy: 'real functionality only',
    counts: { companies: 1, concepts: 1, questions: 1 },
    categories: {
      // Deliberately out of contract order: flattening must impose a stable order.
      questions: [
        entity({
          id: 'Q-1',
          label: 'Net sales · ISS-1 FY2023',
          description: 'Ask Atlas; it may refuse if the cell is not unique',
          category: 'questions',
          action: { kind: 'question', issuer_id: 'ISS-1', concept: 'revenue', period: '2023' },
        }),
      ],
      companies: [entity()],
      concepts: [
        entity({
          id: 'revenue',
          label: 'revenue',
          description: 'income flow',
          category: 'concepts',
          action: { kind: 'concept', concept: 'revenue', statement: 'income' },
        }),
      ],
    },
  }
}

beforeEach(() => {
  clearRecents()
})

describe('command index search', () => {
  it('flattens categories in a stable contract order', () => {
    const flat = flattenIndex(payload())
    expect(flat.map((item) => item.category)).toEqual(['companies', 'concepts', 'questions'])
  })

  it('returns nothing for an empty query: recents are a separate row set', () => {
    expect(searchEntities(payload(), '')).toEqual([])
    expect(searchEntities(null, 'aapl')).toEqual([])
  })

  it('ranks a label prefix above a description match', () => {
    const results = searchEntities(payload(), 'revenue')
    expect(results[0].id).toBe('revenue')
  })

  it('finds an entity by a word inside its label or its category', () => {
    expect(searchEntities(payload(), 'net sales')[0].id).toBe('Q-1')
    expect(searchEntities(payload(), 'concepts').map((item) => item.id)).toContain('revenue')
  })

  it('respects the result limit', () => {
    const results = searchEntities(payload(), 'a', 1)
    expect(results).toHaveLength(1)
  })

  it('builds only in-app routes and refuses anything else', () => {
    expect(actionPath({ kind: 'navigate', path: '/answers' })).toBe('/answers')
    expect(actionPath({ kind: 'navigate', path: 'https://evil.example' })).toBeNull()
    expect(
      actionPath({ kind: 'question', issuer_id: 'ISS 1', concept: 'revenue', period: '2023' }),
    ).toBe('/answers?issuer=ISS%201&concept=revenue&period=2023')
    expect(actionPath({ kind: 'concept', concept: 'net_income', statement: 'income' })).toBe(
      '/answers?concept=net_income',
    )
    expect(actionPath({ kind: 'model', model: 'add' })).toBe('/studio?model=add')
    expect(actionPath({ kind: 'strategy', object_id: 'URO-STR-1' })).toBe('/lab?object=URO-STR-1')
  })
})

describe('recent activity', () => {
  it('de-duplicates by category and id and keeps the newest first', () => {
    recordRecent(entity())
    recordRecent(entity({ id: 'ISS-2', label: 'MSFT' }))
    recordRecent(entity())
    const recents = loadRecents()
    expect(recents.map((item) => item.id)).toEqual(['ISS-1', 'ISS-2'])
  })

  it('is bounded so the palette stays a launcher', () => {
    for (let index = 0; index < 12; index += 1) {
      recordRecent(entity({ id: `ISS-${index}`, label: `Issuer ${index}` }))
    }
    expect(loadRecents()).toHaveLength(8)
  })

  it('survives unreadable storage instead of breaking the palette', () => {
    try {
      window.localStorage?.setItem(RECENTS_KEY, 'not json')
    } catch {
      /* an environment without writable storage is exactly what this test tolerates */
    }
    expect(loadRecents()).toEqual([])
  })
})
