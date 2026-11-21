import { useState } from 'react'
import { Markdown } from '../markdown'
import type { ChatItem, ChatMetadata } from '../types'
import {
  AlertIcon,
  BoltIcon,
  CheckIcon,
  ChipIcon,
  ClockIcon,
  CopyIcon,
  DatabaseIcon,
  KeyIcon,
  RetryIcon,
  SparkIcon,
  TokensIcon,
} from './icons'

function MetaRow({ metadata }: { metadata: ChatMetadata }) {
  const isCache = metadata.resolution_source === 'LLM_CACHE'
  const failedOver = metadata.fallback_attempts > 0
  // Icons and labels sit OUTSIDE the data-testid elements, so each element's text is exactly the value.
  return (
    <div className="meta" aria-label="Response details">
      <span className="meta-group">
        <span className={`badge ${isCache ? 'badge-cache' : 'badge-live'}`} title="Where this reply came from">
          {isCache ? <DatabaseIcon size={12} /> : <BoltIcon size={12} />}
          <span data-testid="meta-source">{metadata.resolution_source}</span>
        </span>
        <span className="chip" title="Model">
          <ChipIcon size={12} />
          <span data-testid="meta-model">{metadata.model}</span>
        </span>
        <span className="chip" title="Server-side latency">
          <ClockIcon size={12} />
          <span data-testid="meta-latency">{metadata.latency_ms} ms</span>
        </span>
      </span>
      <span className="meta-group">
        <span className="chip" title="Tokens for this request only">
          <TokensIcon size={12} />
          <span className="chip-label">in</span>
          <span data-testid="meta-input-tokens">{metadata.input_tokens}</span>
          <span className="chip-sep">·</span>
          <span className="chip-label">out</span>
          <span data-testid="meta-output-tokens">{metadata.output_tokens}</span>
        </span>
        <span className="chip" title="API key that answered (none for cache hits)">
          <KeyIcon size={12} />
          <span data-testid="meta-key-id">{metadata.key_id ?? 'none'}</span>
        </span>
        <span className={`chip ${failedOver ? 'chip-warn' : ''}`} title="Keys that failed before one answered">
          <RetryIcon size={12} />
          <span data-testid="meta-fallback-attempts">{metadata.fallback_attempts}</span>
          <span className="chip-label">{metadata.fallback_attempts === 1 ? 'fallback' : 'fallbacks'}</span>
        </span>
      </span>
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard needs a secure context; ignore elsewhere.
    }
  }
  return (
    <button type="button" className="icon-button copy" onClick={copy} aria-label="Copy reply">
      {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />}
    </button>
  )
}

function AssistantAvatar({ tone = 'default' }: { tone?: 'default' | 'error' }) {
  return (
    <div className={`avatar ${tone === 'error' ? 'avatar-error' : ''}`} aria-hidden="true">
      {tone === 'error' ? <AlertIcon size={16} /> : <SparkIcon size={16} />}
    </div>
  )
}

export function MessageItem({ item }: { item: ChatItem }) {
  switch (item.kind) {
    case 'user':
      return (
        <div className="row row-user">
          <div className="bubble bubble-user" data-testid="user-message">
            <div className="text">{item.content}</div>
          </div>
        </div>
      )
    case 'assistant':
      return (
        <div className="row row-assistant">
          <AssistantAvatar />
          <div className="bubble bubble-assistant" data-testid="assistant-message">
            <CopyButton text={item.content} />
            <div className="text markdown">
              <Markdown text={item.content} />
            </div>
            <MetaRow metadata={item.metadata} />
          </div>
        </div>
      )
    case 'error':
      return (
        <div className="row row-assistant">
          <AssistantAvatar tone="error" />
          <div className="bubble bubble-error" role="alert" data-testid="error-message">
            <div className="text">{item.message}</div>
          </div>
        </div>
      )
  }
}

export function PendingMessage() {
  return (
    <div className="row row-assistant">
      <AssistantAvatar />
      <div className="bubble bubble-pending" data-testid="pending-message" aria-live="polite">
        <span className="dot" />
        <span className="dot" />
        <span className="dot" />
        <span className="sr-only">Thinking…</span>
      </div>
    </div>
  )
}
