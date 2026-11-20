import type { ChatItem, ChatMetadata } from '../types'

function MetaRow({ metadata }: { metadata: ChatMetadata }) {
  const isCache = metadata.resolution_source === 'LLM_CACHE'
  // Labels sit OUTSIDE the data-testid elements so each element's text is exactly the value.
  return (
    <div className="meta" aria-label="Response details">
      <span className={`badge ${isCache ? 'badge-cache' : 'badge-live'}`} data-testid="meta-source">
        {metadata.resolution_source}
      </span>
      <span className="meta-item" title="Model">
        <span className="meta-label">model</span> <span data-testid="meta-model">{metadata.model}</span>
      </span>
      <span className="meta-item" title="Server-side latency">
        <span className="meta-label">latency</span> <span data-testid="meta-latency">{metadata.latency_ms} ms</span>
      </span>
      <span className="meta-item" title="Input tokens for this request">
        <span className="meta-label">in</span> <span data-testid="meta-input-tokens">{metadata.input_tokens}</span>
      </span>
      <span className="meta-item" title="Output tokens for this request">
        <span className="meta-label">out</span> <span data-testid="meta-output-tokens">{metadata.output_tokens}</span>
      </span>
      <span className="meta-item" title="API key that answered (none for cache hits)">
        <span className="meta-label">key</span> <span data-testid="meta-key-id">{metadata.key_id ?? 'none'}</span>
      </span>
      <span className={`meta-item ${metadata.fallback_attempts > 0 ? 'meta-warn' : ''}`} title="Keys that failed first">
        <span className="meta-label">fallbacks</span>{' '}
        <span data-testid="meta-fallback-attempts">{metadata.fallback_attempts}</span>
      </span>
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
          <div className="bubble bubble-assistant" data-testid="assistant-message">
            <div className="text">{item.content}</div>
            <MetaRow metadata={item.metadata} />
          </div>
        </div>
      )
    case 'error':
      return (
        <div className="row row-assistant">
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
      <div className="bubble bubble-pending" data-testid="pending-message" aria-live="polite">
        <span className="dot" />
        <span className="dot" />
        <span className="dot" />
        <span className="sr-only">Thinking…</span>
      </div>
    </div>
  )
}
