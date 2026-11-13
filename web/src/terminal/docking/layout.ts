/** Docking layout model for the Advanced workstation.
 *
 * A layout is data. It mirrors `atlas.workspace.v2` exactly: splits carry
 * directions and normalised weights, tab groups hold panel ids, and every panel
 * appears once. The server validates the same grammar, so a saved layout either
 * renders as reviewed or is refused by both sides.
 *
 * Every operation here is pure: it returns a new tree, which keeps undo, dirty
 * tracking and tests simple.
 */

export type Direction = 'row' | 'column'

export interface TabsNode {
  type: 'tabs'
  active: string
  panels: string[]
}

export interface SplitNode {
  type: 'split'
  direction: Direction
  weights: number[]
  children: LayoutNode[]
}

export type LayoutNode = TabsNode | SplitNode

export type DockSide = 'tab' | 'left' | 'right' | 'top' | 'bottom'

export interface LayoutIssue {
  code: string
  message: string
  context?: Record<string, unknown>
}

export type LayoutResult = { ok: true; layout: LayoutNode } | { ok: false; error: LayoutIssue }

export const MAX_LAYOUT_DEPTH = 5
export const MAX_LAYOUT_NODES = 40
export const MAX_TABS_PER_GROUP = 8
export const MIN_WEIGHT = 0.05
export const MIN_VISIBLE_WEIGHT = 0.08
const EPSILON = 1e-6

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T

function issue(code: string, message: string, context?: Record<string, unknown>): LayoutIssue {
  return { code, message, context }
}

export function isTabs(node: LayoutNode): node is TabsNode {
  return node.type === 'tabs'
}

export function isSplit(node: LayoutNode): node is SplitNode {
  return node.type === 'split'
}

/** Round to the precision the server stores, then force an exact sum of 1. */
export function normalizeWeights(weights: number[]): number[] {
  const total = weights.reduce((sum, value) => sum + value, 0)
  if (!Number.isFinite(total) || total <= 0) return weights.map(() => 1 / weights.length)
  const rounded = weights.map((value) => Math.round((value / total) * 1e6) / 1e6)
  rounded[rounded.length - 1] = Math.round((1 - rounded.slice(0, -1).reduce((sum, value) => sum + value, 0)) * 1e6) / 1e6
  return rounded
}

export function collectPanels(layout: LayoutNode): string[] {
  if (isTabs(layout)) return [...layout.panels]
  return layout.children.flatMap((child) => collectPanels(child))
}

export function countNodes(layout: LayoutNode): number {
  if (isTabs(layout)) return 1
  return 1 + layout.children.reduce((sum, child) => sum + countNodes(child), 0)
}

export function layoutDepth(layout: LayoutNode): number {
  if (isTabs(layout)) return 1
  return 1 + Math.max(...layout.children.map((child) => layoutDepth(child)))
}

export function tabGroupPaths(layout: LayoutNode): number[][] {
  if (isTabs(layout)) return [[]]
  return layout.children.flatMap((child, index) =>
    tabGroupPaths(child).map((path) => [index, ...path]),
  )
}

export function getAtPath(layout: LayoutNode, path: number[]): LayoutNode | null {
  let node: LayoutNode = layout
  for (const step of path) {
    if (!isSplit(node) || !node.children[step]) return null
    node = node.children[step]
  }
  return node
}

export function replaceAtPath(layout: LayoutNode, path: number[], next: LayoutNode): LayoutNode {
  if (path.length === 0) return next
  if (!isSplit(layout)) return next
  const [head, ...rest] = path
  const children = layout.children.map((child, index) =>
    index === head ? replaceAtPath(child, rest, next) : child,
  )
  return { ...layout, children }
}

export function locateTabs(layout: LayoutNode, panelId: string): number[] | null {
  for (const path of tabGroupPaths(layout)) {
    const node = getAtPath(layout, path)
    if (node && isTabs(node) && node.panels.includes(panelId)) return path
  }
  return null
}

export function validateLayout(raw: unknown, panelIds: string[]): LayoutResult {
  const known = new Set(panelIds)
  const placed: string[] = []
  let nodes = 0

  const walk = (value: unknown, depth: number): { node: LayoutNode } | { error: LayoutIssue } => {
    if (depth > MAX_LAYOUT_DEPTH) {
      return { error: issue('layout_too_deep', `Layout is nested deeper than ${MAX_LAYOUT_DEPTH} levels.`) }
    }
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return { error: issue('layout_node_invalid', 'Layout node must be an object.') }
    }
    nodes += 1
    if (nodes > MAX_LAYOUT_NODES) {
      return { error: issue('layout_too_large', `Layout has more than ${MAX_LAYOUT_NODES} nodes.`) }
    }
    const record = value as Record<string, unknown>
    const keys = Object.keys(record)
    if (record.type === 'tabs') {
      const unknown = keys.filter((key) => !['type', 'active', 'panels'].includes(key))
      if (unknown.length) {
        return { error: issue('layout_unknown_key', `Unknown tab group field: ${unknown.join(', ')}.`) }
      }
      const panels = record.panels
      if (!Array.isArray(panels) || panels.length < 1 || panels.length > MAX_TABS_PER_GROUP) {
        return { error: issue('layout_tabs_size', `A tab group needs 1 to ${MAX_TABS_PER_GROUP} panels.`) }
      }
      for (const panelId of panels) {
        if (typeof panelId !== 'string' || !known.has(panelId)) {
          return { error: issue('layout_unknown_panel', `Layout references an unknown panel: ${String(panelId)}.`) }
        }
        if (placed.includes(panelId)) {
          return { error: issue('layout_duplicate_panel', `Panel ${panelId} appears twice in the layout.`) }
        }
        placed.push(panelId)
      }
      if (new Set(panels).size !== panels.length) {
        return { error: issue('layout_duplicate_panel', 'A tab group repeats a panel.') }
      }
      const active = typeof record.active === 'string' ? record.active : (panels[0] as string)
      if (!panels.includes(active)) {
        return { error: issue('layout_active_missing', `Active panel ${active} is not in its group.`) }
      }
      return { node: { type: 'tabs', active, panels: panels as string[] } }
    }
    if (record.type === 'split') {
      const unknown = keys.filter((key) => !['type', 'direction', 'weights', 'children'].includes(key))
      if (unknown.length) {
        return { error: issue('layout_unknown_key', `Unknown split field: ${unknown.join(', ')}.`) }
      }
      if (record.direction !== 'row' && record.direction !== 'column') {
        return { error: issue('layout_direction', 'Split direction must be row or column.') }
      }
      const children = record.children
      if (!Array.isArray(children) || children.length < 2 || children.length > 6) {
        return { error: issue('layout_split_size', 'A split needs 2 to 6 children.') }
      }
      const weights = record.weights
      if (!Array.isArray(weights) || weights.length !== children.length) {
        return { error: issue('layout_weights_length', 'Split weights must match the number of children.') }
      }
      if (weights.some((weight) => typeof weight !== 'number' || !Number.isFinite(weight) || weight < MIN_WEIGHT || weight > 1 - MIN_WEIGHT)) {
        return { error: issue('layout_weight_range', `Split weights must be between ${MIN_WEIGHT} and ${1 - MIN_WEIGHT}.`) }
      }
      const total = (weights as number[]).reduce((sum, weight) => sum + weight, 0)
      if (Math.abs(total - 1) > EPSILON) {
        return { error: issue('layout_weight_sum', 'Split weights must sum to 1.') }
      }
      const built: LayoutNode[] = []
      for (const child of children) {
        const result = walk(child, depth + 1)
        if ('error' in result) return result
        built.push(result.node)
      }
      return {
        node: {
          type: 'split',
          direction: record.direction,
          weights: normalizeWeights(weights as number[]),
          children: built,
        },
      }
    }
    return { error: issue('layout_node_type', 'Unknown layout node type.') }
  }

  const result = walk(raw, 1)
  if ('error' in result) return { ok: false, error: result.error }
  const missing = panelIds.filter((panelId) => !placed.includes(panelId))
  if (missing.length) {
    return {
      ok: false,
      error: issue('layout_orphan', `Layout does not place every panel: ${missing.join(', ')}.`, { missing }),
    }
  }
  return { ok: true, layout: result.node }
}

/** Arrangement implied by a column/span grid (v1 documents and the first open). */
export function deriveLayout(panels: Array<{ id: string; span?: number }>, columns = 3): LayoutNode {
  const rows: Array<Array<{ id: string; span: number }>> = []
  let current: Array<{ id: string; span: number }> = []
  let used = 0
  for (const panel of panels) {
    const span = Math.max(1, Math.min(panel.span ?? 1, columns))
    if (current.length && used + span > columns) {
      rows.push(current)
      current = []
      used = 0
    }
    current.push({ id: panel.id, span })
    used += span
    if (used >= columns) {
      rows.push(current)
      current = []
      used = 0
    }
  }
  if (current.length) rows.push(current)

  const rowNode = (entries: Array<{ id: string; span: number }>): LayoutNode => {
    if (entries.length === 1) return { type: 'tabs', active: entries[0].id, panels: [entries[0].id] }
    const total = entries.reduce((sum, entry) => sum + entry.span, 0)
    return {
      type: 'split',
      direction: 'row',
      weights: normalizeWeights(entries.map((entry) => entry.span / total)),
      children: entries.map((entry) => ({ type: 'tabs', active: entry.id, panels: [entry.id] })),
    }
  }

  if (rows.length === 1) return rowNode(rows[0])
  return {
    type: 'split',
    direction: 'column',
    weights: normalizeWeights(rows.map((row) => row.length / Math.max(1, panels.length))),
    children: rows.map(rowNode),
  }
}

export function activateTab(layout: LayoutNode, path: number[], panelId: string): LayoutNode {
  const node = getAtPath(layout, path)
  if (!node || !isTabs(node) || !node.panels.includes(panelId)) return layout
  return replaceAtPath(layout, path, { ...node, active: panelId })
}

export function removePanel(layout: LayoutNode, panelId: string): LayoutNode | null {
  const prune = (node: LayoutNode): LayoutNode | null => {
    if (isTabs(node)) {
      const panels = node.panels.filter((id) => id !== panelId)
      if (!panels.length) return null
      return { type: 'tabs', active: panels.includes(node.active) ? node.active : panels[0], panels }
    }
    const kept: LayoutNode[] = []
    const weights: number[] = []
    node.children.forEach((child, index) => {
      const next = prune(child)
      if (next) {
        kept.push(next)
        weights.push(node.weights[index] ?? 1 / node.children.length)
      }
    })
    if (!kept.length) return null
    if (kept.length === 1) return kept[0]
    return { type: 'split', direction: node.direction, weights: normalizeWeights(weights), children: kept }
  }
  return prune(layout)
}

export function addTab(layout: LayoutNode, path: number[], panelId: string): LayoutNode {
  const node = getAtPath(layout, path)
  if (!node || !isTabs(node) || node.panels.includes(panelId)) return layout
  if (node.panels.length >= MAX_TABS_PER_GROUP) return layout
  return replaceAtPath(layout, path, { type: 'tabs', active: panelId, panels: [...node.panels, panelId] })
}

export function splitBeside(
  layout: LayoutNode,
  path: number[],
  side: 'left' | 'right' | 'top' | 'bottom',
  panelId: string,
): LayoutNode {
  const node = getAtPath(layout, path)
  if (!node || !isTabs(node)) return layout
  const direction: Direction = side === 'left' || side === 'right' ? 'row' : 'column'
  const inserted: TabsNode = { type: 'tabs', active: panelId, panels: [panelId] }
  const children = side === 'left' || side === 'top' ? [inserted, node] : [node, inserted]
  return replaceAtPath(layout, path, {
    type: 'split',
    direction,
    weights: [0.5, 0.5],
    children,
  })
}

/** Move a panel next to another one: docked as a tab, or split to a side. */
export function movePanelBeside(
  layout: LayoutNode,
  movingId: string,
  anchorId: string,
  side: DockSide,
): LayoutNode {
  if (movingId === anchorId) return layout
  const withoutPanel = removePanel(clone(layout), movingId)
  if (!withoutPanel) return layout
  const anchorPath = locateTabs(withoutPanel, anchorId)
  if (!anchorPath) return layout
  if (side === 'tab') {
    const anchor = getAtPath(withoutPanel, anchorPath)
    if (anchor && isTabs(anchor) && anchor.panels.length < MAX_TABS_PER_GROUP) {
      return addTab(withoutPanel, anchorPath, movingId)
    }
    return splitBeside(withoutPanel, anchorPath, 'right', movingId)
  }
  return splitBeside(withoutPanel, anchorPath, side, movingId)
}

/** Drag a splitter. `delta` is a fraction of the parent's size, positive right/down. */
export function resizeWeights(layout: LayoutNode, path: number[], index: number, delta: number): LayoutNode {
  const node = getAtPath(layout, path)
  if (!node || !isSplit(node)) return layout
  const weights = [...node.weights]
  if (index < 0 || index >= weights.length - 1) return layout
  const pair = weights[index] + weights[index + 1]
  if (pair < MIN_VISIBLE_WEIGHT * 2) return layout
  const nextFirst = Math.min(pair - MIN_VISIBLE_WEIGHT, Math.max(MIN_VISIBLE_WEIGHT, weights[index] + delta))
  weights[index] = nextFirst
  weights[index + 1] = pair - nextFirst
  return replaceAtPath(layout, path, { ...node, weights: normalizeWeights(weights) })
}

export function activePanel(layout: LayoutNode): string | null {
  if (isTabs(layout)) return layout.active
  for (const child of layout.children) {
    const found = activePanel(child)
    if (found) return found
  }
  return null
}

export function layoutSummary(layout: LayoutNode): { panels: number; groups: number; depth: number } {
  return { panels: collectPanels(layout).length, groups: tabGroupPaths(layout).length, depth: layoutDepth(layout) }
}

const SERIAL_VERSION = 2

export function serializeLayout(layout: LayoutNode): string {
  return JSON.stringify({ version: SERIAL_VERSION, layout })
}

export function parseSerializedLayout(text: string, panelIds: string[]): LayoutResult {
  let payload: unknown
  try {
    payload = JSON.parse(text)
  } catch {
    return { ok: false, error: issue('layout_not_json', 'Saved layout is not valid JSON.') }
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return { ok: false, error: issue('layout_not_json', 'Saved layout must be an object.') }
  }
  const record = payload as Record<string, unknown>
  if (record.version !== SERIAL_VERSION) {
    return {
      ok: false,
      error: issue('layout_version', `Unsupported saved layout version: ${String(record.version)}.`),
    }
  }
  return validateLayout(record.layout, panelIds)
}

/** Default six-panel desk: monitor and chart on top, statements, metrics and evidence below. */
export function defaultWorkstationLayout(panelIds: string[]): LayoutNode {
  const ids = panelIds.length ? panelIds : ['monitor']
  if (ids.length <= 2) {
    return {
      type: 'split',
      direction: 'column',
      weights: normalizeWeights(ids.map(() => 1 / ids.length)),
      children: ids.map((id) => ({ type: 'tabs', active: id, panels: [id] })),
    }
  }
  const top = ids.slice(0, 2)
  const bottom = ids.slice(2)
  return {
    type: 'split',
    direction: 'column',
    weights: [0.56, 0.44],
    children: [
      {
        type: 'split',
        direction: 'row',
        weights: normalizeWeights([0.42, 0.58]),
        children: top.map((id) => ({ type: 'tabs', active: id, panels: [id] })),
      },
      {
        type: 'split',
        direction: 'row',
        weights: normalizeWeights(bottom.map(() => 1 / bottom.length)),
        children: bottom.map((id) => ({ type: 'tabs', active: id, panels: [id] })),
      },
    ],
  }
}
