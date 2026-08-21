/**
 * Typed access to the admin surface.
 *
 * The server guards these routes with HTTP Basic and nothing else, so this
 * module carries the credentials on every call. Two deliberate consequences:
 *
 * * **Credentials live in React state only.** Never `localStorage`, never
 *   `sessionStorage`. A reload therefore asks for the password again, which is
 *   the price of never writing an administrator's password to disk in a
 *   browser that anyone might later sit down at.
 * * **A rejection is reported exactly as the server words it.** The server
 *   answers "wrong password", "unknown user", and "admin not configured"
 *   identically on purpose; distinguishing them here would undo that.
 */

import { ApiError } from './client'
import type { ErrorBody } from './types'

const BASE = '/api/v1/admin'

export type AdminCredentials = { username: string; password: string }

export type Metric = {
  value: unknown
  sample_size: number
  unit: string | null
  no_data: boolean
}

export type DashboardPayload = {
  window_days: number
  since: string
  metrics: Record<string, Metric>
}

export type FeedbackEntry = {
  id: string
  created_at: string
  stage: 'faq' | 'chat'
  outcome: 'resolved' | 'unresolved'
  reason: string | null
  question: string
  note: string | null
  source_urls: string[]
  conversation_id: string | null
  message_id: string | null
  answer: string | null
}

export type FeedbackPage = { total: number; items: FeedbackEntry[] }

function authorization({ username, password }: AdminCredentials): string {
  // `btoa` handles Latin-1 only, and a password may hold anything. Encoding to
  // UTF-8 bytes first keeps a non-ASCII password from throwing here rather than
  // failing as a wrong password, which would be an infuriating thing to debug.
  const bytes = new TextEncoder().encode(`${username}:${password}`)
  let binary = ''
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return `Basic ${btoa(binary)}`
}

async function adminRequest<T>(
  path: string,
  credentials: AdminCredentials,
  init?: RequestInit,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        Authorization: authorization(credentials),
        ...(init?.headers ?? {}),
      },
    })
  } catch (cause) {
    console.warn('admin request could not reach the API', cause)
    throw new ApiError(
      'NETWORK_UNAVAILABLE',
      'ارتباط با سرویس برقرار نشد. اتصال شبکه را بررسی کنید.',
      0,
    )
  }

  if (response.status === 401) {
    throw new ApiError('ADMIN_UNAUTHORIZED', 'احراز هویت مدیر لازم است.', 401)
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
  return (await response.json()) as T
}

export function fetchDashboard(
  credentials: AdminCredentials,
  windowDays: number,
): Promise<DashboardPayload> {
  return adminRequest<DashboardPayload>(
    `/dashboard?window_days=${windowDays}&top_n=10`,
    credentials,
  )
}

export function fetchFeedback(
  credentials: AdminCredentials,
  options: { windowDays: number; stage?: 'faq' | 'chat'; outcome?: 'resolved' | 'unresolved' },
): Promise<FeedbackPage> {
  const query = new URLSearchParams({
    window_days: String(options.windowDays),
    limit: '100',
  })
  if (options.stage) query.set('stage', options.stage)
  if (options.outcome) query.set('outcome', options.outcome)
  return adminRequest<FeedbackPage>(`/feedback?${query.toString()}`, credentials)
}
