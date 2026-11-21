import { useState } from 'react'
import type { Health } from '../api'
import { CheckIcon, CopyIcon, PlusIcon, SparkIcon } from './icons'

export type HealthState = { kind: 'checking' } | { kind: 'online'; health: Health } | { kind: 'offline' }

interface HeaderProps {
  sessionId: string
  health: HealthState
  onNewChat: () => void
  disabled: boolean
}

function HealthPill({ health }: { health: HealthState }) {
  const label =
    health.kind === 'online'
      ? `Online · ${health.health.keys_configured} keys${health.health.cache_enabled ? ' · cache on' : ''}`
      : health.kind === 'offline'
        ? 'Backend unreachable'
        : 'Connecting…'
  return (
    <span className={`status status-${health.kind}`} data-testid="health-status" title="Backend /health">
      <span className="status-dot" />
      {label}
    </span>
  )
}

export function Header({ sessionId, health, onNewChat, disabled }: HeaderProps) {
  const [copied, setCopied] = useState(false)

  async function copySessionId() {
    try {
      await navigator.clipboard.writeText(sessionId)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard needs a secure context; the id is still visible and selectable.
    }
  }

  return (
    <header className="header">
      <div className="brand">
        <div className="logo" aria-hidden="true">
          <SparkIcon size={20} />
        </div>
        <div className="brand-text">
          <h1>Lyftr Chat</h1>
          <p className="tagline">Multi-key LLM gateway with failover and caching</p>
        </div>
      </div>

      <div className="header-actions">
        <HealthPill health={health} />
        <div className="session" title={`Session id (new on every page load): ${sessionId}`}>
          <span className="session-label">Session</span>
          <code data-testid="session-id">{sessionId}</code>
          <button type="button" className="icon-button" onClick={copySessionId} aria-label="Copy session id">
            {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />}
          </button>
        </div>
        <button type="button" className="button button-secondary" onClick={onNewChat} disabled={disabled}>
          <PlusIcon size={16} />
          New chat
        </button>
      </div>
    </header>
  )
}
