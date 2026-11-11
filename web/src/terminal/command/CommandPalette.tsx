import { useEffect, useMemo, useRef, useState } from 'react'
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
  onRun: (command: AtlasCommand) => void
}

export default function CommandPalette({ open, onClose, context, onRun }: PaletteProps) {
  const [value, setValue] = useState('')
  const [index, setIndex] = useState(0)
  const [error, setError] = useState<CommandError | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  const suggestions = useMemo(
    () => (open ? completeCommands(value, context) : []),
    [open, value, context],
  )

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

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setIndex((current) => Math.min(current + 1, Math.max(0, suggestions.length - 1)))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setIndex((current) => Math.max(0, current - 1))
      return
    }
    if (event.key === 'Tab') {
      event.preventDefault()
      const suggestion = suggestions[index]
      if (suggestion) setValue(suggestion.value)
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      const typed = value.trim()
      if (typed) {
        execute(typed)
        return
      }
      const suggestion = suggestions[index]
      if (suggestion) execute(suggestion.value)
    }
  }

  return (
    <div className="palette-scrim" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={onClose}>
      <div className="palette" onMouseDown={(event) => event.stopPropagation()}>
        <input
          ref={inputRef}
          className="palette-input"
          aria-label="Atlas command"
          placeholder="AAPL  ·  JPM FIN  ·  SET ASOF 2024-06-01  ·  WORKSPACE …"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          autoComplete="off"
          spellCheck={false}
        />
        <div className="palette-hint">
          Enter to run · Tab to complete · ↑ ↓ to choose · Esc to close. Commands act on real Atlas data only.
        </div>
        <ul className="palette-list" ref={listRef} role="listbox">
          {suggestions.map((suggestion, position) => (
            <li
              key={`${suggestion.kind}-${suggestion.value}`}
              role="option"
              aria-selected={position === index}
              className={`palette-item ${position === index ? 'is-active' : ''}`}
              onMouseEnter={() => setIndex(position)}
              onMouseDown={(event) => {
                event.preventDefault()
                execute(suggestion.value)
              }}
            >
              <strong>{suggestion.label}</strong>
              <span>
                {suggestion.description} · {suggestion.kind}
              </span>
            </li>
          ))}
          {!suggestions.length && <li className="palette-item">No matching command.</li>}
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
