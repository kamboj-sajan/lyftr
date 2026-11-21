import { useEffect, useRef, useState } from 'react'
import { API_BASE_URL, ChatError, fetchHealth, sendChat } from './api'
import { Composer } from './components/Composer'
import { EmptyState } from './components/EmptyState'
import { Header, type HealthState } from './components/Header'
import { SlidersIcon } from './components/icons'
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
  const [health, setHealth] = useState<HealthState>({ kind: 'checking' })
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const endRef = useRef<HTMLDivElement>(null)

  // Also wakes a sleeping free-tier backend as soon as the page opens.
  useEffect(() => {
    let cancelled = false
    fetchHealth().then((result) => {
      if (!cancelled) setHealth(result ? { kind: 'online', health: result } : { kind: 'offline' })
    })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    // Only follow the conversation; on an empty chat keep the welcome screen at the top.
    if (items.length > 0 || pending) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [items, pending])

  async function send(text: string) {
    const message = text.trim()
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
    <div className="shell">
      <div className="app">
        <Header sessionId={sessionId} health={health} onNewChat={handleNewChat} disabled={pending} />

        <section className="settings" aria-label="Session settings">
          <label className="setting" htmlFor="system-prompt">
            <span className="setting-label">
              <SlidersIcon size={14} />
              System prompt
            </span>
            <input
              id="system-prompt"
              type="text"
              data-testid="system-prompt-input"
              placeholder="Optional, e.g. You are a concise travel guide."
              title="Sent with each message; the server keeps it for this session."
              value={systemPrompt}
              onChange={(event) => setSystemPrompt(event.target.value)}
            />
          </label>
        </section>

        <main className="messages" aria-live="polite">
          <div className="messages-inner">
            {items.length === 0 && !pending && <EmptyState onPick={send} disabled={pending} />}
            {items.map((item) => (
              <MessageItem key={item.id} item={item} />
            ))}
            {pending && <PendingMessage />}
            <div ref={endRef} />
          </div>
        </main>

        <footer className="footer">
          <Composer
            ref={inputRef}
            value={input}
            onChange={setInput}
            onSend={() => send(input)}
            pending={pending}
          />
          <p className="api-base">
            API <code>{API_BASE_URL}</code>
          </p>
        </footer>
      </div>
    </div>
  )
}
