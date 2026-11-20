import { forwardRef, type KeyboardEvent } from 'react'

const MAX_CHARS = 4000

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  pending: boolean
}

export const Composer = forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(
  { value, onChange, onSend, pending },
  ref,
) {
  const length = value.trim().length
  const canSend = !pending && length > 0

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter is a newline, and Enter that confirms an IME composition is ignored.
    if (event.key !== 'Enter' || event.shiftKey) return
    if (event.nativeEvent.isComposing || event.keyCode === 229) return
    event.preventDefault()
    if (canSend) onSend()
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault()
        if (canSend) onSend()
      }}
    >
      <label className="sr-only" htmlFor="chat-input">
        Message
      </label>
      <textarea
        id="chat-input"
        ref={ref}
        data-testid="chat-input"
        className="composer-input"
        placeholder="Type a message… (Enter to send, Shift+Enter for a new line)"
        rows={2}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      <div className="composer-side">
        <span className={`counter ${length > MAX_CHARS ? 'counter-over' : ''}`} aria-live="polite">
          {length}/{MAX_CHARS}
        </span>
        <button type="submit" className="send" data-testid="send-button" disabled={!canSend}>
          {pending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </form>
  )
})
