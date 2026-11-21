import { forwardRef, useLayoutEffect, useRef, type KeyboardEvent } from 'react'
import { SendIcon } from './icons'

const MAX_CHARS = 4000
const MAX_HEIGHT_PX = 200

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  pending: boolean
}

export const Composer = forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(
  { value, onChange, onSend, pending },
  forwardedRef,
) {
  const localRef = useRef<HTMLTextAreaElement | null>(null)
  const length = value.trim().length
  const canSend = !pending && length > 0
  const over = length > MAX_CHARS

  // Grow with the content up to MAX_HEIGHT_PX, then scroll.
  useLayoutEffect(() => {
    const el = localRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`
  }, [value])

  function setRefs(el: HTMLTextAreaElement | null) {
    localRef.current = el
    if (typeof forwardedRef === 'function') forwardedRef(el)
    else if (forwardedRef) forwardedRef.current = el
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter is a newline, and Enter that confirms an IME composition is ignored.
    if (event.key !== 'Enter' || event.shiftKey) return
    if (event.nativeEvent.isComposing || event.keyCode === 229) return
    event.preventDefault()
    if (canSend) onSend()
  }

  return (
    <div className="composer-wrap">
      <form
        className={`composer ${over ? 'composer-over' : ''}`}
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
          ref={setRefs}
          data-testid="chat-input"
          className="composer-input"
          placeholder="Message Lyftr Chat…"
          rows={1}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          type="submit"
          className={`send ${pending ? 'send-pending' : ''}`}
          data-testid="send-button"
          disabled={!canSend}
          aria-label={pending ? 'Sending…' : 'Send message'}
          title="Send (Enter)"
        >
          {pending ? <span className="spinner" aria-hidden="true" /> : <SendIcon size={18} />}
        </button>
      </form>
      <div className="composer-hint">
        <span>
          <kbd>Enter</kbd> to send · <kbd>Shift</kbd> + <kbd>Enter</kbd> for a new line
        </span>
        <span className={`counter ${over ? 'counter-over' : ''}`} aria-live="polite">
          {length.toLocaleString()} / {MAX_CHARS.toLocaleString()}
        </span>
      </div>
    </div>
  )
})
