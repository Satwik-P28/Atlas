import { useEffect, useMemo, useRef, useState } from 'react'
import type { CommandIndexPayload } from '../../api'
import { categoryLabel, searchEntities, type PaletteEntity } from './indexSearch'
import {
  completeCommands,
  parseCommand,
  type AtlasCommand,
  type CommandContext,
  type CommandError,
} from './registry'

interface PaletteProps {
  open: boolean
  onClose: () => void
  context: CommandContext
  index?: CommandIndexPayload | null
  recents?: PaletteEntity[]
  onRun: (command: AtlasCommand) => void
  onRunEntity?: (entity: PaletteEntity) => void
}

type Row =
  | { kind: 'recent'; key: string; label: string; description: string; entity: PaletteEntity }
  | { kind: 'command'; key: string; label: string; description: string; value: string }
  | { kind: 'entity'; key: string; label: string; description: string; entity: PaletteEntity }

/** The palette is one launcher over the command grammar and the live entity index.
 * Commands act on the workstation; entities navigate to a real route or ask a real
 * question. Nothing here is a placeholder, and an entity that is not in the database is
 * not offered. */
export default function CommandPalette({
  open,
  onClose,
  context,
  index,
  recents = [],
  onRun,
  onRunEntity,
}: PaletteProps) {
  const [value, setValue] = useState('')
  const [index_, setIndex] = useState(0)
  const [error, setError] = useState<CommandError | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  const rows = useMemo<Row[]>(() => {
    if (!open) return []
    const trimmed = value.trim()
    const out: Row[] = []
    if (!trimmed) {
      for (const entity of recents.slice(0, 5)) {
        out.push({
          kind: 'recent',
          key: `recent:${entity.category}:${entity.id}`,
          label: entity.label,
          description: `${entity.description} · ${categoryLabel(entity.category)}`,
          entity,
        })
      }
    }
    for (const suggestion of completeCommands(value, context)) {
      out.push({
        kind: 'command',
        key: `command:${suggestion.kind}:${suggestion.value}`,
        label: suggestion.label,
        description: `${suggestion.description} · command`,
        value: suggestion.value,
      })
    }
    for (const entity of searchEntities(index ?? null, trimmed, 8)) {
      out.push({
        kind: 'entity',
        key: `entity:${entity.category}:${entity.id}`,
        label: entity.label,
        description: `${entity.description} · ${categoryLabel(entity.category)}`,
        entity,
      })
    }
    return out
  }, [open, value, context, index, recents])

  useEffect(() => {
    if (!open) return
    setValue('')
    setIndex(0)
    setError(null)
    const handle = window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => window.clearTimeout(handle)
  }, [open])

  useEffect(() => {
    setIndex(0)
  }, [value])

  useEffect(() => {
    const active = listRef.current?.querySelector<HTMLElement>('.palette-item.is-active')
    active?.scrollIntoView({ block: 'nearest' })
  }, [index_])

  if (!open) return null

  function execute(text: string) {
    const parsed = parseCommand(text, context)
    if (!parsed.ok) {
      setError(parsed.error)
      return
    }
    setError(null)
    onRun(parsed.command)
    onClose()
  }

  function runRow(row: Row) {
    if (row.kind === 'command') {
      execute(row.value)
      return
    }
    onRunEntity?.(row.entity)
    onClose()
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setIndex((current) => Math.min(current + 1, Math.max(0, rows.length - 1)))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setIndex((current) => Math.max(0, current - 1))
      return
    }
    if (event.key === 'Tab') {
      event.preventDefault()
      const row = rows[index_]
      if (row && row.kind === 'command') setValue(row.value)
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      const typed = value.trim()
      const row = rows[index_]
      if (typed) {
        // Prefer a matching command when the user typed a command; otherwise the
        // top-scored entity is the clearer interpretation of a name.
        if (row && row.kind === 'command' && row.label.toLowerCase().startsWith(typed.toLowerCase())) {
          execute(typed)
          return
        }
        const parsed = parseCommand(typed, context)
        if (parsed.ok) {
          execute(typed)
          return
        }
        if (row) {
          runRow(row)
          return
        }
        setError(parsed.error)
        return
      }
      if (row) runRow(row)
    }
  }

  return (
    <div
      className="palette-scrim"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      onMouseDown={onClose}
    >
      <div className="palette" onMouseDown={(event) => event.stopPropagation()}>
        <input
          ref={inputRef}
          className="palette-input"
          aria-label="Atlas command or search"
          placeholder="AAPL  ·  revenue  ·  10-K  ·  SET ASOF 2024-06-01  ·  WORKSPACE …"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          autoComplete="off"
          spellCheck={false}
        />
        <div className="palette-hint">
          Enter to run · Tab to complete · ↑ ↓ to choose · Esc to close. Every result is a real route, a
          real question or a saved object in this database.
          {index ? ` ${Object.values(index.counts).reduce((total, count) => total + count, 0)} indexed.` : ''}
        </div>
        <ul className="palette-list" ref={listRef} role="listbox">
          {rows.map((row, position) => (
            <li
              key={row.key}
              role="option"
              aria-selected={position === index_}
              className={`palette-item ${position === index_ ? 'is-active' : ''}`}
              onMouseEnter={() => setIndex(position)}
              onMouseDown={(event) => {
                event.preventDefault()
                runRow(row)
              }}
            >
              <strong>{row.label}</strong>
              <span>
                {row.description}
                {row.kind === 'recent' ? ' · recent' : ''}
              </span>
            </li>
          ))}
          {!rows.length && (
            <li className="palette-item">
              {value.trim()
                ? 'Nothing matches. Atlas does not invent an entity; check the name or the cutoff.'
                : 'Type a ticker, concept, filing, model, strategy or saved research.'}
            </li>
          )}
        </ul>
        {error && (
          <div className="palette-error" role="alert">
            <strong>{error.message}</strong>
            {error.hint && <span>{error.hint}</span>}
            {error.candidates && error.candidates.length > 0 && (
              <div className="palette-candidates">
                {error.candidates.map((candidate) => (
                  <button
                    key={candidate}
                    className="button"
                    onMouseDown={(event) => {
                      event.preventDefault()
                      setValue(candidate)
                      setError(null)
                    }}
                  >
                    {candidate}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
