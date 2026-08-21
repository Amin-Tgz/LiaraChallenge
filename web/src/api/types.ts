/** Wire types. These mirror the FastAPI response models exactly. */

export type ErrorBody = { error: { code: string; message: string } }

export type FaqResult = {
  faq_item_id: string
  question: string
  answer: string
  similarity: number
  source_url: string
  source_commit: string | null
  tags: string[]
}

export type FaqSearchResponse = {
  results: FaqResult[]
  rescue_tools_available: boolean
}

export type Citation = {
  evidence_id: string
  url: string
  page_title: string | null
  section_title: string | null
  source_commit: string | null
}

export type ChatImage = {
  evidence_id?: string | null
  url: string
  alt?: string | null
  caption?: string | null
  ordinal?: number | null
  heading_anchor?: string | null
}

/** Why an answer fell short. Mirrors `FeedbackReason`. */
export type FeedbackReason =
  | 'incorrect'
  | 'incomplete'
  | 'irrelevant'
  | 'wrong_source'
  | 'other'

export type FeedbackOutcome = 'resolved' | 'unresolved'

export type MessageFeedback = {
  outcome: FeedbackOutcome
  reason: FeedbackReason | null
}

export type Message = {
  id: string
  ordinal: number
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  citations: Citation[]
  images: ChatImage[]
  error_code: string | null
  /** A verdict this browser already gave, so a reload does not re-ask. */
  feedback: MessageFeedback | null
}

/**
 * Mirrors `JobStatus`. `retrying` is deliberately visible: a user watching a
 * slow answer is owed the truth about what is happening to it.
 */
export type JobStatus =
  | 'queued'
  | 'retrieving'
  | 'generating'
  | 'retrying'
  | 'completed'
  | 'failed'

export type Job = {
  id: string
  conversation_id: string
  status: JobStatus
  attempt: number
  max_attempts: number
  error_code: string | null
  message: string | null
  result_message_id: string | null
}

export type AskResponse = {
  conversation_id: string
  job: Job
  created: boolean
}

export type ConversationSummary = {
  id: string
  initial_question: string
  title: string | null
  rescue_tool: string | null
  message_count: number
}

export type ConversationDetail = {
  id: string
  initial_question: string
  title: string | null
  technical_profile: Record<string, unknown>
  rescue_tool: string | null
  messages: Message[]
  jobs: Job[]
}

export type RescueToolName = 'skill' | 'mcp' | 'chat'

/** Relay event payloads, one per `JobEventType`. */
export type StatusEvent = {
  status: JobStatus
  attempt: number
  max_attempts?: number
  error_code?: string
  message?: string
}
export type DeltaEvent = { text: string }
/**
 * One step the agent took looking for evidence.
 *
 * Commentary on the work rather than part of the answer: it lives only on the
 * relay stream, so a reload mid-answer replays it and a finished conversation
 * does not carry it.
 */
export type TraceEvent = {
  step: number
  tool: string
  query: string | null
  result_count: number | null
  top_similarity: number | null
  status: 'ok' | 'limit'
  elapsed_ms: number
}
export type FinalEvent = {
  message_id: string
  answer: string
  citations: Citation[]
  images: ChatImage[]
  needs_clarification: boolean
  clarification_field: string | null
  tool_calls: number
  rewrites: number
  error_code?: string
  message?: string
}
export type ErrorEvent = {
  error_code: string
  message: string
  attempts: number
  retryable: boolean
}
