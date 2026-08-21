/**
 * Typed access to the rescue API.
 *
 * Everything is same-origin — the bundle is served by the API itself — so no
 * CORS and no cross-site cookie configuration is involved. The session cookie
 * rides along automatically and is never read by this code; when an endpoint
 * needs the session id, it comes from `GET /api/v1/session`.
 */

import type {
  AskResponse,
  ConversationDetail,
  ConversationSummary,
  ErrorBody,
  FaqSearchResponse,
  FeedbackOutcome,
  FeedbackReason,
  Job,
  RescueToolName,
} from './types'

const BASE = '/api/v1'

/**
 * An API failure that still knows its own cause.
 *
 * The server never returns a generic failure, so neither does this: `code` is
 * the taxonomy identifier and `message` is the Persian text meant for a user.
 */
export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

const UNREACHABLE = 'ارتباط با سرویس برقرار نشد. اتصال شبکه را بررسی کنید.'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch (cause) {
    // A transport failure is its own cause and must not be reported as though
    // the server had rejected the request. The original is kept for the
    // console; only the Persian message is ever shown.
    console.warn('request could not reach the API', cause)
    throw new ApiError('NETWORK_UNAVAILABLE', UNREACHABLE, 0)
  }

  if (!response.ok) {
    let body: ErrorBody | null = null
    try {
      body = (await response.json()) as ErrorBody
    } catch {
      body = null
    }
    throw new ApiError(
      body?.error.code ?? 'INTERNAL_ERROR',
      body?.error.message ?? 'خطای غیرمنتظره‌ای رخ داد.',
      response.status,
    )
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function getSessionId(): Promise<{ session_id: string }> {
  return request<{ session_id: string }>('/session')
}

export function searchFaq(question: string): Promise<FaqSearchResponse> {
  return request<FaqSearchResponse>('/faq/search', {
    method: 'POST',
    body: JSON.stringify({ question }),
  })
}

export function startConversation(
  question: string,
  idempotencyKey: string,
): Promise<AskResponse> {
  return request<AskResponse>('/chat/conversations', {
    method: 'POST',
    body: JSON.stringify({ question, idempotency_key: idempotencyKey }),
  })
}

export function sendMessage(
  conversationId: string,
  question: string,
  idempotencyKey: string,
): Promise<AskResponse> {
  return request<AskResponse>(`/chat/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ question, idempotency_key: idempotencyKey }),
  })
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/chat/conversations/${id}`)
}

export function listConversations(): Promise<ConversationSummary[]> {
  return request<ConversationSummary[]>('/chat/conversations')
}

export function deleteConversation(id: string): Promise<void> {
  return request<void>(`/chat/conversations/${id}`, { method: 'DELETE' })
}

export function getJob(id: string): Promise<Job> {
  return request<Job>(`/chat/jobs/${id}`)
}

/**
 * Judge one answer.
 *
 * Only the verdict is sent. The question and the documentation pages the answer
 * relied on are read server-side from the message itself, so this call cannot
 * mis-attribute a complaint to the wrong page.
 */
export function submitMessageFeedback(
  messageId: string,
  payload: { outcome: FeedbackOutcome; reason?: FeedbackReason; note?: string },
): Promise<{ feedback_id: string }> {
  return request<{ feedback_id: string }>(`/chat/messages/${messageId}/feedback`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function recordFeedback(payload: {
  session_id: string
  conversation_id?: string | null
  question: string
  outcome: 'resolved' | 'unresolved'
  presented_faq_ids: string[]
}): Promise<unknown> {
  return request('/feedback', { method: 'POST', body: JSON.stringify(payload) })
}

export function recordInteraction(payload: {
  event_type: 'faq_impression' | 'faq_selection' | 'rescue_tool_transition'
  session_id: string
  conversation_id?: string | null
  question: string
  faq_item_ids?: string[]
  rescue_tool?: RescueToolName | null
}): Promise<unknown> {
  return request('/faq/interactions', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/**
 * Analytics must never cost the user their answer.
 *
 * Telemetry runs alongside the flow, so a failing analytics call is logged and
 * dropped rather than surfaced or retried.
 */
export function fireAndForget(promise: Promise<unknown>): void {
  promise.catch((cause: unknown) => {
    console.warn('telemetry call failed and was dropped', cause)
  })
}

/** A client-side idempotency key, so a retried submission is provably the same one. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function jobEventsUrl(jobId: string): string {
  return `${BASE}/chat/jobs/${jobId}/events`
}
