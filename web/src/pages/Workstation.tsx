import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useSettings } from '../state'
import type { PanelConfig, WorkspaceDocument } from '../types'
import Workbench from '../terminal/docking/Workbench'
import {
  MAX_TABS_PER_GROUP,
  activateTab,
  activePanel,
  addTab,
  defaultWorkstationLayout,
  deriveLayout,
  getAtPath,
  isTabs,
  layoutSummary,
  locateTabs,
  movePanelBeside,
  removePanel,
  splitBeside,
  validateLayout,
  type DockSide,
  type LayoutNode,
} from '../terminal/docking/layout'
import type { PanelKind } from '../terminal/command/registry'
import { resolveInstrument, type LinkGroup } from '../terminal/links'
import { useLinks } from '../terminal/linkContext'
import {
  PANEL_META,
  PANEL_ORDER,
  PanelView,
  backendTypeFor,
  panelKindFromBackend,
  type PanelDescriptor,
} from '../terminal/panels/registry'

const DEFAULT_PANELS: PanelDescriptor[] = [
  { id: 'monitor', kind: 'monitor', title: 'Universe', linkGroup: null },
  { id: 'chart', kind: 'chart', title: 'Price', linkGroup: 'A' },
  { id: 'statements', kind: 'statements', title: 'Statements', linkGroup: 'A' },
  { id: 'metrics', kind: 'metrics', title: 'Metrics', linkGroup: 'A' },
  { id: 'evidence', kind: 'evidence', title: 'Evidence', linkGroup: null },
  { id: 'memo', kind: 'memo', title: 'Memos', linkGroup: 'A' },
]

function insertPanel(layout: LayoutNode, panelId: string): LayoutNode {
  const anchorId = activePanel(layout)
  const path = anchorId ? locateTabs(layout, anchorId) : null
  if (!path) return defaultWorkstationLayout([panelId])
  const node = getAtPath(layout, path)
  if (node && isTabs(node) && node.panels.length < MAX_TABS_PER_GROUP) return addTab(layout, path, panelId)
  return splitBeside(layout, path, 'right', panelId)
}

export default function Workstation() {
  const { mode, setMode } = useSettings()
  const links = useLinks()
  const navigate = useNavigate()
  const { workspaceId: routeId } = useParams<{ workspaceId?: string }>()

  const [panels, setPanels] = useState<PanelDescriptor[]>(DEFAULT_PANELS)
  const [layout, setLayout] = useState<LayoutNode>(() => defaultWorkstationLayout(DEFAULT_PANELS.map((panel) => panel.id)))
  const [maximized, setMaximized] = useState<string | null>(null)
  const [name, setName] = useState('Desk')
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ tone: 'ok' | 'warn' | 'bad'; text: string } | null>(null)
  const [addKind, setAddKind] = useState<PanelKind>('statements')

  useEffect(() => {
    if (!routeId) return
    let cancelled = false
    api
      .workspace(routeId)
      .then((workspace) => {
        if (cancelled) return
        const descriptors: PanelDescriptor[] = []
        for (const panel of workspace.document.panels ?? []) {
          const kind = panelKindFromBackend(panel.type)
          if (!kind) continue
          descriptors.push({
            id: panel.id,
            kind,
            title: panel.title,
            linkGroup: (panel.link_group as LinkGroup | null) ?? null,
          })
        }
        if (!descriptors.length) {
          setNotice({ tone: 'bad', text: 'This workspace contains no panel type Atlas can render.' })
          return
        }
        const ids = descriptors.map((descriptor) => descriptor.id)
        const derived = deriveLayout(descriptors.map((descriptor) => ({ id: descriptor.id, span: 1 })), 3)
        const raw = (workspace.document as { layout?: unknown }).layout
        const parsed = raw ? validateLayout(raw, ids) : { ok: true as const, layout: derived }
        setPanels(descriptors)
        setName(workspace.name)
        setWorkspaceId(workspace.workspace_id)
        setDirty(false)
        setMaximized(null)
        if (parsed.ok) {
          setLayout(parsed.layout)
          setNotice(null)
        } else {
          setLayout(derived)
          setNotice({
            tone: 'warn',
            text: `The saved layout was rejected (${parsed.error.message}). Atlas derived a safe arrangement from the panel list instead of guessing.`,
          })
        }
      })
      .catch((error: Error) => setNotice({ tone: 'bad', text: error.message }))
    return () => {
      cancelled = true
    }
  }, [routeId])

  function updateLayout(next: LayoutNode) {
    setLayout(next)
    setDirty(true)
  }

  function ensurePanel(kind: PanelKind) {
    const existing = panels.find((panel) => panel.kind === kind)
    if (existing) {
      setMaximized(null)
      const path = locateTabs(layout, existing.id)
      if (path) updateLayout(activateTab(layout, path, existing.id))
      return
    }
    const id = `${kind}-${Math.random().toString(36).slice(2, 6)}`
    const descriptor: PanelDescriptor = {
      id,
      kind,
      title: PANEL_META[kind].title,
      linkGroup: ['statements', 'metrics', 'chart', 'memo'].includes(kind) ? links.state.activeGroup : null,
    }
    setPanels((current) => [...current, descriptor])
    updateLayout(insertPanel(layout, id))
  }

  function closePanel(panelId: string) {
    const remaining = panels.filter((panel) => panel.id !== panelId)
    setPanels(remaining)
    if (maximized === panelId) setMaximized(null)
    const next = removePanel(layout, panelId)
    if (next) {
      updateLayout(next)
    } else {
      setLayout(defaultWorkstationLayout([]))
      setDirty(true)
    }
  }

  function movePanel(movingId: string, anchorId: string, side: DockSide) {
    const next = movePanelBeside(layout, movingId, anchorId, side)
    if (next !== layout) updateLayout(next)
  }

  function resetDesk() {
    setPanels(DEFAULT_PANELS)
    setLayout(defaultWorkstationLayout(DEFAULT_PANELS.map((panel) => panel.id)))
    setMaximized(null)
    setName('Desk')
    setWorkspaceId(null)
    setDirty(false)
    setSelectedEvidence(null)
    setNotice({ tone: 'ok', text: 'Default desk restored. Open a saved workspace from the command palette to return to a stored layout.' })
    if (routeId) navigate('/workstation')
  }

  async function persistWorkspace(document: WorkspaceDocument) {
    if (workspaceId) return api.updateWorkspace(workspaceId, document)
    // Workspace names are unique in the store. A collision is normal (two desks
    // named "Desk"), so try a suffixed name instead of failing the save.
    let next = document
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await api.createWorkspace(next)
      } catch (error) {
        const status = (error as { status?: number }).status
        if (status !== 409 || attempt >= 4) throw error
        next = { ...next, name: `${next.name.replace(/ \d+$/, '')} ${attempt + 2}` }
      }
    }
  }

  async function save() {
    if (busy) return
    setBusy(true)
    setNotice(null)
    try {
      const ids = panels.map((panel) => panel.id)
      const checked = validateLayout(layout, ids)
      if (!checked.ok) {
        setNotice({ tone: 'bad', text: `Layout refused: ${checked.error.message}` })
        return
      }
      const payloadPanels = panels.map((panel) => {
        const selection = resolveInstrument(links.state, panel.linkGroup)
        const base: Record<string, unknown> = {
          id: panel.id,
          type: backendTypeFor(panel.kind),
          title: panel.title,
          span: 1,
          config: {},
          link_group: panel.linkGroup,
        }
        if (panel.kind === 'statements' || panel.kind === 'metrics') {
          if (!selection.issuerId) {
            throw new Error(`Panel “${panel.title}” needs an instrument in link group ${panel.linkGroup ?? 'A'} before it can be saved.`)
          }
          base.issuer_id = selection.issuerId
        }
        if (panel.kind === 'chart') {
          if (!selection.securityId) {
            throw new Error(`Panel “${panel.title}” needs a priced security in link group ${panel.linkGroup ?? 'A'} before it can be saved.`)
          }
          base.security_id = selection.securityId
        }
        return base
      })
      let targetName = name.trim() || 'Desk'
      if (!workspaceId) {
        // Names are unique in the store. Choose a free one before creating, so a
        // collision is not a failed request the analyst has to interpret.
        const existing = await api.workspaces()
        const taken = new Set(existing.items.map((item) => item.name.toLowerCase()))
        const base = targetName.replace(/ \d+$/, '')
        let suffix = 2
        while (taken.has(targetName.toLowerCase())) {
          targetName = `${base} ${suffix}`
          suffix += 1
        }
      }
      const document: WorkspaceDocument = {
        name: targetName,
        mode: 'advanced',
        columns: 3,
        description: 'Advanced workstation layout',
        schema: 'atlas.workspace.v2',
        panels: payloadPanels as unknown as PanelConfig[],
        layout: checked.layout,
      }
      const saved = await persistWorkspace(document)
      setWorkspaceId(saved.workspace_id)
      setName(saved.name)
      setDirty(false)
      setNotice({ tone: 'ok', text: `Saved “${saved.name}” · fingerprint ${saved.fingerprint} · ${saved.document.panels.length} panels` })
    } catch (error) {
      setNotice({ tone: 'bad', text: (error as Error).message })
    } finally {
      setBusy(false)
    }
  }

  // Re-registered every render on purpose: the palette and keyboard shortcuts
  // must call the newest save/reset handlers, never a stale closure.
  useEffect(() => {
    const onSave = () => void save()
    const onReset = () => resetDesk()
    const onPanel = (event: Event) => ensurePanel((event as CustomEvent<PanelKind>).detail)
    window.addEventListener('atlas:save', onSave)
    window.addEventListener('atlas:reset', onReset)
    window.addEventListener('atlas:panel', onPanel)
    return () => {
      window.removeEventListener('atlas:save', onSave)
      window.removeEventListener('atlas:reset', onReset)
      window.removeEventListener('atlas:panel', onPanel)
    }
  })

  if (mode !== 'advanced') {
    return (
      <div className="page">
        <h1>Advanced workstation</h1>
        <p className="muted">
          The dockable desk, command palette and link groups belong to Advanced mode. Switching modes does not change any
          research data or calculation.
        </p>
        <button className="button button-primary" onClick={() => setMode('advanced')}>
          Enable Advanced mode
        </button>
      </div>
    )
  }

  const summary = layoutSummary(layout)
  const chrome = Object.fromEntries(
    panels.map((panel) => [panel.id, { title: panel.title, kind: panel.kind, linkGroup: panel.linkGroup }]),
  )

  return (
    <div className="ws">
      <div className="ws-toolbar">
        <input
          className="field"
          aria-label="Workspace name"
          value={name}
          onChange={(event) => {
            setName(event.target.value)
            setDirty(true)
          }}
          style={{ width: 180 }}
        />
        <span className="ws-meta">
          {summary.panels} panels · {summary.groups} groups · depth {summary.depth} ·{' '}
          {maximized ? `maximized ${maximized}` : 'tiled'}
        </span>
        <span className={`tp-badge ${dirty ? 'is-warn' : 'is-ok'}`}>{dirty ? 'unsaved' : 'saved'}</span>
        <div className="tp-toolbar" style={{ marginLeft: 'auto', marginBottom: 0 }}>
          <select className="field" value={addKind} onChange={(event) => setAddKind(event.target.value as PanelKind)} aria-label="Panel type">
            {PANEL_ORDER.map((kind) => (
              <option key={kind} value={kind}>
                {PANEL_META[kind].title}
              </option>
            ))}
          </select>
          <button className="button" onClick={() => ensurePanel(addKind)}>
            Add panel
          </button>
          <button className="button" onClick={resetDesk}>
            Reset
          </button>
          <button className="button button-primary" onClick={() => void save()} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {notice && (
        <div className={`ws-banner is-${notice.tone}`} role="status">
          {notice.text}{' '}
          <button className="link-button small" onClick={() => setNotice(null)}>
            dismiss
          </button>
        </div>
      )}

      <Workbench
        layout={layout}
        panels={chrome}
        maximized={maximized}
        onMaximize={setMaximized}
        onLayout={updateLayout}
        onActivate={(panelId) => {
          const path = locateTabs(layout, panelId)
          if (path) updateLayout(activateTab(layout, path, panelId))
        }}
        onClosePanel={closePanel}
        onMovePanel={movePanel}
        renderPanel={(panelId) => {
          const descriptor = panels.find((panel) => panel.id === panelId)
          if (!descriptor) return <div className="tp-empty">Panel not found.</div>
          return (
            <PanelView
              descriptor={descriptor}
              selectedEvidence={selectedEvidence}
              onEvidence={setSelectedEvidence}
              onSelectInstrument={(issuerId, securityId) =>
                links.select(descriptor.linkGroup ?? links.state.activeGroup, issuerId, securityId)
              }
            />
          )
        }}
      />
    </div>
  )
}
