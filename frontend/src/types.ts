export type ResolutionSource = 'LIVE_INFERENCE' | 'LLM_CACHE'

export interface Attempt {
  key_id: string
  status: number | null
  outcome: 'success' | 'error' | 'empty'
  simulated: boolean
  ms: number
}

export interface ChatMetadata {
  resolution_source: ResolutionSource
  model: string
  latency_ms: number
  input_tokens: number
  output_tokens: number
  key_id: string | null
  fallback_attempts: number
  attempts?: Attempt[]
}

export interface ChatRequest {
  session_id: string
  message: string
  system_prompt?: string
}

export interface ChatResponse {
  session_id: string
  reply: string
  metadata: ChatMetadata
}

export type ChatItem =
  | { kind: 'user'; id: string; content: string }
  | { kind: 'assistant'; id: string; content: string; metadata: ChatMetadata }
  | { kind: 'error'; id: string; message: string }
