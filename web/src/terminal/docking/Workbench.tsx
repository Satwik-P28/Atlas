import { useRef, useState, type DragEvent, type ReactNode } from 'react'
import {
  isSplit,
  isTabs,
  locateTabs,
  resizeWeights,
  type DockSide,
  type LayoutNode,
} from './layout'

export interface PanelChrome {
  title: string
  kind: string
  linkGroup: string | null
}

interface WorkbenchProps {
  layout: LayoutNode
  panels: Record<string, PanelChrome>
  renderPanel: (panelId: string) => ReactNode
  onLayout: (next: LayoutNode) => void
  onClosePanel: (panelId: string) => void
  onActivate: (panelId: string) => void
  onMovePanel: (movingId: string, anchorId: string, side: DockSide) => void
  maximized: string | null
  onMaximize: (panelId: string | null) => void
}

function dropSide(event: DragEvent<HTMLElement>): DockSide {
  const rect = event.currentTarget.getBoundingClientRect()
  if (!rect.width || !rect.height) return 'tab'
  const x = (event.clientX - rect.left) / rect.width
  const y = (event.clientY - rect.top) / rect.height
  const edge = 0.22
  if (x < edge) return 'left'
  if (x > 1 - edge) return 'right'
  if (y < edge) return 'top'
  if (y > 1 - edge) return 'bottom'
  return 'tab'
}

export default function Workbench({
  layout,
  panels,
  renderPanel,
  onLayout,
  onClosePanel,
  onActivate,
  onMovePanel,
  maximized,
  onMaximize,
}: WorkbenchProps) {
  const [dragging, setDragging] = useState<string | null>(null)
  const maximizedPath = maximized ? locateTabs(layout, maximized) : null

  const node = maximizedPath ? findNode(layout, maximizedPath) : null
  if (node && isTabs(node)) {
    return (
      <div className="wb-root">
        <div className="wb-maximized">
          <TabGroup
            node={node}
            layout={layout}
            onLayout={onLayout}
            panels={panels}
            renderPanel={renderPanel}
            onClosePanel={onClosePanel}
            onActivate={onActivate}
            onMovePanel={onMovePanel}
            onMaximize={onMaximize}
            dragging={dragging}
            onDragStart={setDragging}
            onDragEnd={() => setDragging(null)}
            maximized={maximized}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="wb-root">
      <NodeView
        node={layout}
        path={[]}
        layout={layout}
        panels={panels}
        renderPanel={renderPanel}
        onLayout={onLayout}
        onClosePanel={onClosePanel}
        onActivate={onActivate}
        onMovePanel={onMovePanel}
        onMaximize={onMaximize}
        dragging={dragging}
        onDragStart={setDragging}
        onDragEnd={() => setDragging(null)}
        maximized={maximized}
      />
    </div>
  )
}

function findNode(layout: LayoutNode, path: number[]): LayoutNode | null {
  let node: LayoutNode = layout
  for (const step of path) {
    if (!isSplit(node) || !node.children[step]) return null
    node = node.children[step]
  }
  return node
}

interface SharedProps extends WorkbenchProps {
  dragging: string | null
  onDragStart: (panelId: string) => void
  onDragEnd: () => void
}

function NodeView({
  node,
  path,
  layout,
  ...rest
}: SharedProps & { node: LayoutNode; path: number[]; layout: LayoutNode }) {
  if (isTabs(node)) {
    return <TabGroup node={node} path={path} layout={layout} {...rest} />
  }
  return (
    <div className="wb-split" data-direction={node.direction}>
      {node.children.map((child, index) => (
        <div key={`${path.join('-')}-${index}`} className="wb-pane" style={{ flexGrow: node.weights[index] ?? 1 }}>
          <NodeView node={child} path={[...path, index]} layout={layout} {...rest} />
          {index < node.children.length - 1 && (
            <Splitter
              direction={node.direction}
              layout={layout}
              path={path}
              index={index}
              onLayout={rest.onLayout}
            />
          )}
        </div>
      ))}
    </div>
  )
}

function Splitter({
  direction,
  layout,
  path,
  index,
  onLayout,
}: {
  direction: 'row' | 'column'
  layout: LayoutNode
  path: number[]
  index: number
  onLayout: (next: LayoutNode) => void
}) {
  const [active, setActive] = useState(false)
  const last = useRef(0)

  return (
    <div
      className={`wb-splitter ${active ? 'is-dragging' : ''}`}
      role="separator"
      aria-orientation={direction === 'row' ? 'vertical' : 'horizontal'}
      aria-label="Resize panels"
      tabIndex={0}
      onPointerDown={(event) => {
        ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
        last.current = direction === 'row' ? event.clientX : event.clientY
        setActive(true)
      }}
      onPointerMove={(event) => {
        if (!active) return
        const parent = event.currentTarget.parentElement
        if (!parent) return
        const rect = parent.getBoundingClientRect()
        const total = direction === 'row' ? rect.width : rect.height
        if (!total) return
        const position = direction === 'row' ? event.clientX : event.clientY
        const delta = (position - last.current) / total
        if (!delta) return
        last.current = position
        onLayout(resizeWeights(layout, path, index, delta))
      }}
      onPointerUp={(event) => {
        setActive(false)
        ;(event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId)
      }}
      onKeyDown={(event) => {
        const step = event.shiftKey ? 0.1 : 0.02
        if (direction === 'row' && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
          event.preventDefault()
          onLayout(resizeWeights(layout, path, index, event.key === 'ArrowRight' ? step : -step))
        }
        if (direction === 'column' && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
          event.preventDefault()
          onLayout(resizeWeights(layout, path, index, event.key === 'ArrowDown' ? step : -step))
        }
      }}
    />
  )
}

function TabGroup({
  node,
  panels,
  renderPanel,
  onClosePanel,
  onActivate,
  onMovePanel,
  onMaximize,
  dragging,
  onDragStart,
  onDragEnd,
  maximized,
}: SharedProps & { node: { type: 'tabs'; active: string; panels: string[] }; path?: number[]; layout?: LayoutNode }) {
  const [hover, setHover] = useState<DockSide | null>(null)
  const panel = panels[node.active]

  return (
    <section className="wb-group" aria-label={panel?.title ?? 'Panel group'}>
      <div
        className="wb-tabs"
        role="tablist"
        onDragOver={(event) => {
          if (!dragging) return
          event.preventDefault()
        }}
        onDrop={(event) => {
          event.preventDefault()
          const moving = event.dataTransfer.getData('text/atlas-panel') || dragging
          if (moving) onMovePanel(moving, node.active, 'tab')
          onDragEnd()
        }}
      >
        {node.panels.map((panelId) => {
          const meta = panels[panelId]
          const active = panelId === node.active
          return (
            <div
              key={panelId}
              className={`wb-tab ${active ? 'is-active' : ''}`}
              role="tab"
              aria-selected={active}
              tabIndex={active ? 0 : -1}
              draggable
              onDragStart={(event) => {
                event.dataTransfer.setData('text/atlas-panel', panelId)
                event.dataTransfer.effectAllowed = 'move'
                onDragStart(panelId)
              }}
              onDragEnd={onDragEnd}
              onClick={() => onActivate(panelId)}
              onKeyDown={(event) => {
                const index = node.panels.indexOf(panelId)
                if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
                  event.preventDefault()
                  const next = (index + (event.key === 'ArrowRight' ? 1 : node.panels.length - 1)) % node.panels.length
                  onActivate(node.panels[next])
                }
                if (event.key === 'Enter' || event.key === ' ') onActivate(panelId)
              }}
            >
              {meta?.linkGroup && <span className={`link-dot is-${meta.linkGroup.toLowerCase()}`} title={`Link group ${meta.linkGroup}`} />}
              <span>{meta?.title ?? panelId}</span>
              <button
                className="wb-tab-close"
                aria-label={`Close ${meta?.title ?? panelId}`}
                onClick={(event) => {
                  event.stopPropagation()
                  onClosePanel(panelId)
                }}
              >
                ×
              </button>
            </div>
          )
        })}
        <div className="wb-tab-group-actions">
          <button
            className="wb-icon-button"
            aria-label={maximized ? 'Restore panel' : 'Maximize panel'}
            title={maximized ? 'Restore panel' : 'Maximize panel'}
            onClick={() => onMaximize(maximized ? null : node.active)}
          >
            {maximized ? '❐' : '⤢'}
          </button>
        </div>
      </div>
      <div
        className={`wb-body ${hover ? 'is-drop-target' : ''}`}
        onDragOver={(event) => {
          if (!dragging) return
          event.preventDefault()
          setHover(dropSide(event))
        }}
        onDragLeave={() => setHover(null)}
        onDrop={(event) => {
          event.preventDefault()
          const moving = event.dataTransfer.getData('text/atlas-panel') || dragging
          const side = dropSide(event)
          setHover(null)
          if (moving) onMovePanel(moving, node.active, side)
          onDragEnd()
        }}
      >
        {hover && hover !== 'tab' && <DropIndicator side={hover} />}
        {renderPanel(node.active)}
      </div>
    </section>
  )
}

function DropIndicator({ side }: { side: Exclude<DockSide, 'tab'> }) {
  const style: Record<string, string | number> = { top: 0, left: 0, width: '100%', height: '100%' }
  if (side === 'left') style.width = '50%'
  if (side === 'right') {
    style.width = '50%'
    style.left = '50%'
  }
  if (side === 'top') style.height = '50%'
  if (side === 'bottom') {
    style.height = '50%'
    style.top = '50%'
  }
  return <div className="wb-drop-zone" style={style} aria-hidden />
}
