import { describe, expect, it } from 'vitest'
import {
  activePanel,
  addTab,
  collectPanels,
  defaultWorkstationLayout,
  deriveLayout,
  getAtPath,
  isTabs,
  layoutSummary,
  locateTabs,
  movePanelBeside,
  splitBeside,
  parseSerializedLayout,
  removePanel,
  resizeWeights,
  serializeLayout,
  validateLayout,
  type LayoutNode,
} from './layout'

const row = (weights: number[], children: LayoutNode[]): LayoutNode => ({
  type: 'split',
  direction: 'row',
  weights,
  children,
})

const tabs = (active: string, panels: string[]): LayoutNode => ({ type: 'tabs', active, panels })

describe('layout validation', () => {
  it('accepts a docked layout and keeps its direction and weights', () => {
    const layout = row([0.6, 0.4], [tabs('a', ['a']), tabs('b', ['b', 'c'])])
    const result = validateLayout(layout, ['a', 'b', 'c'])
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.layout).toMatchObject({ type: 'split', direction: 'row', weights: [0.6, 0.4] })
  })

  it('refuses a layout that does not place every panel', () => {
    const result = validateLayout(tabs('a', ['a']), ['a', 'b'])
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.error.code).toBe('layout_orphan')
    expect(result.error.context?.missing).toEqual(['b'])
  })

  it('refuses a repeated panel', () => {
    const layout = row([0.5, 0.5], [tabs('a', ['a']), tabs('a', ['a'])])
    const result = validateLayout(layout, ['a', 'b'])
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error.code).toBe('layout_duplicate_panel')
  })

  it('refuses weights that do not sum to one', () => {
    const layout = row([0.5, 0.6], [tabs('a', ['a']), tabs('b', ['b'])])
    const result = validateLayout(layout, ['a', 'b'])
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error.code).toBe('layout_weight_sum')
  })

  it('refuses unknown fields and unknown node types', () => {
    const withEval = { type: 'tabs', active: 'a', panels: ['a'], eval: 'alert(1)' }
    expect(validateLayout(withEval, ['a']).ok).toBe(false)
    expect(validateLayout({ type: 'grid', panels: ['a'] }, ['a']).ok).toBe(false)
  })

  it('refuses an active panel outside its group', () => {
    const result = validateLayout({ type: 'tabs', active: 'b', panels: ['a'] }, ['a', 'b'])
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error.code).toBe('layout_active_missing')
  })
})

describe('grid derivation', () => {
  it('turns spans into weighted rows', () => {
    const layout = deriveLayout([{ id: 'a', span: 2 }, { id: 'b', span: 1 }], 3)
    expect(layout.type).toBe('split')
    if (layout.type !== 'split') return
    expect(layout.weights).toEqual([0.666667, 0.333333])
    expect(collectPanels(layout)).toEqual(['a', 'b'])
  })

  it('stacks rows when panels exceed the column count', () => {
    const layout = deriveLayout([{ id: 'a' }, { id: 'b' }, { id: 'c' }, { id: 'd' }], 3)
    expect(layout.type).toBe('split')
    if (layout.type !== 'split') return
    expect(layout.direction).toBe('column')
    expect(collectPanels(layout)).toEqual(['a', 'b', 'c', 'd'])
  })
})

describe('desk operations', () => {
  const base = row([0.5, 0.5], [tabs('a', ['a']), tabs('b', ['b'])])

  it('docks a panel beside another as a split', () => {
    const next = movePanelBeside(base, 'a', 'b', 'left')
    expect(collectPanels(next)).toEqual(['a', 'b'])
    const path = locateTabs(next, 'a')
    expect(path).not.toBeNull()
    if (path) expect(getAtPath(next, path)).toMatchObject({ type: 'tabs', panels: ['a'] })
    expect(getAtPath(next, [])).toMatchObject({ type: 'split', direction: 'row' })
  })

  it('docks a panel as a tab in the anchor group', () => {
    const withThree = addTab(base, locateTabs(base, 'b') ?? [], 'c')
    const next = movePanelBeside(withThree, 'a', 'b', 'tab')
    const path = locateTabs(next, 'b')
    expect(path).not.toBeNull()
    if (path) expect(getAtPath(next, path)).toMatchObject({ type: 'tabs', panels: ['b', 'c', 'a'], active: 'a' })
  })

  it('collapses a split when the last panel in a group closes', () => {
    const next = removePanel(base, 'b')
    expect(next).toMatchObject({ type: 'tabs', panels: ['a'] })
    expect(removePanel(row([1], [tabs('a', ['a'])]) as LayoutNode, 'a')).toBeNull()
  })

  it('keeps weights summing to one while resizing', () => {
    const next = resizeWeights(base, [], 0, 0.2)
    if (next.type !== 'split') throw new Error('expected split')
    expect(next.weights.reduce((sum, weight) => sum + weight, 0)).toBeCloseTo(1, 6)
    expect(next.weights[0]).toBeCloseTo(0.7, 6)
  })

  it('refuses to collapse a pane below the minimum weight', () => {
    const next = resizeWeights(base, [], 0, -10)
    if (next.type !== 'split') throw new Error('expected split')
    expect(next.weights[0]).toBeGreaterThanOrEqual(0.08 - 1e-9)
  })

  it('splits the active panel out of its tab group', () => {
    const grouped = tabs('b', ['a', 'b'])
    const next = splitBeside(grouped, [], 'right', 'c')
    expect(collectPanels(next)).toEqual(['a', 'b', 'c'])
    // The split keeps the original group intact; the new panel becomes its own pane.
    expect(activePanel(next)).toBe('b')
  })

  it('reports the desk shape', () => {
    expect(layoutSummary(base)).toEqual({ panels: 2, groups: 2, depth: 2 })
  })

  it('builds a default desk that places every panel exactly once', () => {
    const ids = ['a', 'b', 'c', 'd', 'e', 'f']
    const layout = defaultWorkstationLayout(ids)
    const result = validateLayout(layout, ids)
    expect(result.ok).toBe(true)
    expect(collectPanels(layout).sort()).toEqual([...ids].sort())
    expect(isTabs(getAtPath(layout, [0, 0]) as LayoutNode)).toBe(true)
  })
})

describe('serialization', () => {
  it('round-trips a layout', () => {
    const layout = row([0.5, 0.5], [tabs('a', ['a']), tabs('b', ['b'])])
    const parsed = parseSerializedLayout(serializeLayout(layout), ['a', 'b'])
    expect(parsed.ok).toBe(true)
    if (parsed.ok) expect(parsed.layout).toEqual(layout)
  })

  it('refuses unsupported versions and broken JSON', () => {
    const bad = parseSerializedLayout(JSON.stringify({ version: 1, layout: tabs('a', ['a']) }), ['a'])
    expect(bad.ok).toBe(false)
    if (!bad.ok) expect(bad.error.code).toBe('layout_version')
    expect(parseSerializedLayout('{not json', ['a']).ok).toBe(false)
  })

  it('refuses a serialized layout that references a missing panel', () => {
    const parsed = parseSerializedLayout(serializeLayout(tabs('a', ['a'])), ['a', 'b'])
    expect(parsed.ok).toBe(false)
  })
})

describe('phase 9.6.2 single-panel invariants', () => {
  const ids = ['a', 'b', 'c', 'd', 'e', 'f']

  it('collapses six panels down to a valid single tabs node', () => {
    let layout = defaultWorkstationLayout(ids)
    for (const id of ids.slice(1)) {
      layout = removePanel(layout, id) as LayoutNode
    }
    expect(layout.type).toBe('tabs')
    expect(validateLayout(layout, ['a']).ok).toBe(true)
  })

  it('builds a valid one-panel default layout', () => {
    const layout = defaultWorkstationLayout(['a'])
    expect(layout).toEqual({ type: 'tabs', active: 'a', panels: ['a'] })
    expect(validateLayout(layout, ['a']).ok).toBe(true)
  })

  it('grows one panel back to two without a lone split child', () => {
    const one = defaultWorkstationLayout(['a'])
    const two = splitBeside(one, [], 'right', 'b')
    expect(validateLayout(two, ['a', 'b']).ok).toBe(true)
    const again = removePanel(two, 'b') as LayoutNode
    expect(again.type).toBe('tabs')
  })

  it('survives repeated add/remove cycles', () => {
    let layout = defaultWorkstationLayout(['a'])
    for (let cycle = 0; cycle < 5; cycle += 1) {
      layout = splitBeside(layout, [], 'right', 'b')
      layout = removePanel(layout, 'b') as LayoutNode
      expect(validateLayout(layout, ['a']).ok).toBe(true)
    }
  })

  it('closing the active tab keeps a valid active panel', () => {
    const two = splitBeside(defaultWorkstationLayout(['a']), [], 'right', 'b')
    const closed = removePanel(two, 'b') as LayoutNode
    expect(closed.type).toBe('tabs')
    expect(validateLayout(closed, ['a']).ok).toBe(true)
  })
})
