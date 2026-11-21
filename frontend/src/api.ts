import type { ChatRequest, ChatResponse } from './types'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')

const REQUEST_TIMEOUT_MS = 90_000

/** An error whose message is already a readable sentence for the chat window. */
export class ChatError extends Error {}

interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

function describeValidation(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail) || detail.length === 0) return 'the request was not valid'
  return (detail as ValidationIssue[])
    .map((issue) => {
      const field = (issue.loc ?? []).filter((part) => part !== 'body').join('.')
      const msg = (issue.msg ?? 'is invalid').replace(/^Value error, /, '')
      if (!field) return msg
      return msg.toLowerCase().startsWith(field.toLowerCase()) ? msg : `${field}: ${msg}`
    })
    .join('; ')
}

function describeHttpError(status: number, body: unknown): string {
  const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : undefined
  switch (status) {
    case 422:
      return `Your message could not be sent: ${describeValidation(detail)}.`
    case 503:
      return 'All AI providers are unavailable right now (every API key failed). Please try again in a moment.'
    case 500:
      return 'The server hit an unexpected error. Please try again.'
    default:
      return `Request failed with status ${status}${typeof detail === 'string' ? `: ${detail}` : ''}.`
  }
}

export interface Health {
  status: string
  keys_configured: number
  cache_enabled: boolean
}

/** GET /health. Resolves to null when the backend is unreachable or unhealthy. */
export async function fetchHealth(timeoutMs = 75_000): Promise<Health | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${API_BASE_URL}/health`, { signal: controller.signal })
    if (!response.ok) return null
    return (await response.json()) as Health
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

export async function sendChat(request: ChatRequest, simulateFailure?: string): Promise<ChatResponse> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (simulateFailure) headers['X-Simulate-Failure'] = simulateFailure

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify(request),
      signal: controller.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ChatError('The server took too long to answer. Please try again.')
    }
    throw new ChatError(
      `Could not reach the server at ${API_BASE_URL}. Check that the backend is running and allows this origin (CORS).`,
    )
  } finally {
    clearTimeout(timer)
  }

  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) throw new ChatError(describeHttpError(response.status, body))
  if (!body || typeof body !== 'object' || typeof (body as ChatResponse).reply !== 'string') {
    throw new ChatError('The server sent an unexpected response.')
  }
  return body as ChatResponse
}
