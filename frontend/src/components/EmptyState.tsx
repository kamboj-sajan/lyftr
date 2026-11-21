import { BoltIcon, DatabaseIcon, RetryIcon, SparkIcon } from './icons'

const SUGGESTIONS = [
  'What is the capital of France?',
  'My favourite number is 42',
  'Explain response caching in two sentences.',
  'Write a haiku about servers that never go down.',
]

export function EmptyState({ onPick, disabled }: { onPick: (text: string) => void; disabled: boolean }) {
  return (
    <div className="empty">
      <div className="empty-logo" aria-hidden="true">
        <SparkIcon size={28} />
      </div>
      <h2>How can I help today?</h2>
      <p className="empty-sub">
        Every reply shows where it came from, which model and key answered, the latency and the token usage.
      </p>

      <div className="suggestions">
        {SUGGESTIONS.map((text) => (
          <button key={text} type="button" className="suggestion" onClick={() => onPick(text)} disabled={disabled}>
            {text}
          </button>
        ))}
      </div>

      <ul className="features">
        <li>
          <span className="feature-icon feature-live">
            <BoltIcon size={14} />
          </span>
          <span>
            <b>Live inference</b> from the first healthy API key
          </span>
        </li>
        <li>
          <span className="feature-icon feature-cache">
            <DatabaseIcon size={14} />
          </span>
          <span>
            <b>Cache hits</b> in milliseconds: try a question again in a new chat
          </span>
        </li>
        <li>
          <span className="feature-icon feature-retry">
            <RetryIcon size={14} />
          </span>
          <span>
            <b>Automatic failover</b> to the next key on rate limits and errors
          </span>
        </li>
      </ul>
    </div>
  )
}
