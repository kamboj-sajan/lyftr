import { useEffect, useRef, useState } from 'react'
import { API_BASE_URL, ChatError, sendChat } from './api'
import { Composer } from './components/Composer'
import { MessageItem, PendingMessage } from './components/Messages'
import { newSessionId, nextItemId } from './session'
import type { ChatItem } from './types'

export default function App() {
  // A fresh session on every page load: created once in state, never persisted.
  const [sessionId, setSessionId] = useState(newSessionId)
  const [items, setItems] = useState<ChatItem[]>([])
  const [input, setInput] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [pending, setPending] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [items, pending])

  async function handleSend() {
    const message = input.trim()
    if (!message || pending) return

    setItems((prev) => [...prev, { kind: 'user', id: nextItemId(), content: message }])
    setInput('')
    setPending(true)
    try {
      const prompt = systemPrompt.trim()
      const response = await sendChat({
        session_id: sessionId,
        message,
        ...(prompt ? { system_prompt: prompt } : {}),
      })
      setItems((prev) => [
        ...prev,
        { kind: 'assistant', id: nextItemId(), content: response.reply, metadata: response.metadata },
      ])
    } catch (err) {
      const text = err instanceof ChatError ? err.message : 'Something went wrong. Please try again.'
      setItems((prev) => [...prev, { kind: 'error', id: nextItemId(), message: text }])
    } finally {
      setPending(false)
      inputRef.current?.focus()
    }
  }

  function handleNewChat() {
    if (pending) return
    setSessionId(newSessionId())
    setItems([])
    inputRef.current?.focus()
  }

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1>Lyftr Chat</h1>
          <span className="session" title="Session id (new on every page load)">
            session <code data-testid="session-id">{sessionId}</code>
          </span>
        </div>
        <button type="button" className="ghost" onClick={handleNewChat} disabled={pending}>
          New chat
        </button>
      </header>

      <section className="settings" aria-label="Session settings">
        <label className="field">
          <span className="field-label">System prompt (optional, kept for this session)</span>
          <input
            type="text"
            data-testid="system-prompt-input"
            placeholder="e.g. You are a concise travel guide."
            value={systemPrompt}
            onChange={(event) => setSystemPrompt(event.target.value)}
          />
        </label>
      </section>

      <main className="messages" aria-live="polite">
        {items.length === 0 && !pending && (
          <div className="empty">
            <p>Ask anything to start.</p>
            <p className="muted">
              Each reply shows where it came from (<b>LIVE_INFERENCE</b> or <b>LLM_CACHE</b>), the model, latency and
              token usage. Send the same first message in a new chat to see a cache hit.
            </p>
          </div>
        )}
        {items.map((item) => (
          <MessageItem key={item.id} item={item} />
        ))}
        {pending && <PendingMessage />}
        <div ref={endRef} />
      </main>

      <footer className="footer">
        <Composer ref={inputRef} value={input} onChange={setInput} onSend={handleSend} pending={pending} />
        <p className="api-base muted">
          API: <code>{API_BASE_URL}</code>
        </p>
      </footer>
    </div>
  )
}
