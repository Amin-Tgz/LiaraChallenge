/**
 * The conversation.
 *
 * State always comes from the server on mount, never from router state alone.
 * That is what makes a reload during generation restore the transcript and
 * rejoin the running job instead of starting a second one — the URL carries the
 * conversation id, and everything else is reconstructed from it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  ApiError,
  getConversation,
  newIdempotencyKey,
  sendMessage,
} from '../api/client'
import type { ConversationDetail, Job, Message } from '../api/types'
import { useJobStream } from '../api/useJobStream'
import { Citations } from '../components/Citations'
import { JobProgress } from '../components/JobProgress'
import { Markdown } from '../components/Markdown'
import { rememberNextQuestion } from '../flow'
import { submitTextareaOnEnter } from '../keyboard'

const MAX_USER_TURNS = 3

/** A job still owed an answer, if the conversation has one. */
function activeJob(jobs: Job[]): Job | null {
  return (
    jobs.find(
      (job) =>
        job.status === 'queued' ||
        job.status === 'retrieving' ||
        job.status === 'generating' ||
        job.status === 'retrying',
    ) ?? null
  )
}

export default function ChatView() {
  const { conversationId = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const passed = (location.state ?? {}) as { jobId?: string }

  const [conversation, setConversation] = useState<ConversationDetail | null>(null)
  const [jobId, setJobId] = useState<string | null>(passed.jobId ?? null)
  const [followUp, setFollowUp] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const transcriptEnd = useRef<HTMLDivElement | null>(null)

  const stream = useJobStream(jobId)

  const load = useCallback(async () => {
    try {
      const detail = await getConversation(conversationId)
      setConversation(detail)
      // Rejoin whatever is already running rather than starting anything.
      const running = activeJob(detail.jobs)
      if (running) setJobId(running.id)
      return detail
    } catch (cause) {
      setLoadError(
        cause instanceof ApiError ? cause.message : 'ارتباط با سرویس برقرار نشد.',
      )
      return null
    }
  }, [conversationId])

  useEffect(() => {
    void load()
  }, [load])

  // When a job finishes, the persisted transcript is the source of truth.
  useEffect(() => {
    if (stream.done) void load()
  }, [stream.done, load])

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ block: 'end' })
  }, [conversation?.messages.length, stream.answer])

  async function ask(event: React.FormEvent) {
    event.preventDefault()
    const text = followUp.trim()
    if (!text) return
    const userTurns = conversation?.messages.filter((message) => message.role === 'user').length ?? 0
    if (userTurns >= MAX_USER_TURNS) {
      rememberNextQuestion(text)
      navigate('/')
      return
    }
    setError(null)
    try {
      const response = await sendMessage(conversationId, text, newIdempotencyKey())
      setFollowUp('')
      setJobId(response.job.id)
      await load()
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'HISTORY_LIMIT_REACHED') {
        rememberNextQuestion(text)
        navigate('/')
        return
      }
      setError(
        cause instanceof ApiError ? cause.message : 'ارتباط با سرویس برقرار نشد.',
      )
    }
  }

  if (loadError) {
    return (
      <main className="shell">
        <p role="alert" className="job-error">
          {loadError}
        </p>
      </main>
    )
  }

  if (!conversation) {
    return (
      <main className="shell">
        <p role="status">در حال بازیابی گفت‌وگو…</p>
      </main>
    )
  }

  const answered = new Set(
    conversation.jobs
      .map((job) => job.result_message_id)
      .filter((id): id is string => Boolean(id)),
  )
  // While a job runs, its partial answer is not yet a persisted message.
  const streaming = jobId !== null && !stream.done && stream.answer.length > 0
  const userTurns = conversation.messages.filter((message) => message.role === 'user').length
  const atTurnLimit = userTurns >= MAX_USER_TURNS
  const jobRunning = jobId !== null && !stream.done

  return (
    <main className="shell chat">
      <div className="chat-heading">
        <div>
          <span className="eyebrow">پاسخ مبتنی بر شواهد</span>
          <h1>گفت‌وگو</h1>
        </div>
        <span className="turn-counter">نوبت {Math.min(userTurns, MAX_USER_TURNS)} از {MAX_USER_TURNS}</span>
      </div>
      <p className="original-question">
        <span className="label">سؤال اصلی:</span> {conversation.initial_question}
      </p>

      <ol className="transcript">
        {conversation.messages.map((message) => (
          <li key={message.id} className={`turn turn-${message.role}`}>
            <Turn message={message} isAnswer={answered.has(message.id)} />
          </li>
        ))}

        {streaming && (
          <li className="turn turn-assistant">
            <Markdown>{stream.answer}</Markdown>
          </li>
        )}
      </ol>
      <div ref={transcriptEnd} />

      {jobId && !stream.done && (
        <JobProgress
          status={stream.status}
          attempt={stream.attempt}
          maxAttempts={conversation.jobs.find((job) => job.id === jobId)?.max_attempts}
        />
      )}
      {jobId && stream.done && stream.errorCode && (
        <JobProgress
          status="failed"
          errorCode={stream.errorCode}
          errorMessage={stream.errorMessage}
        />
      )}

      <form onSubmit={ask} className={'follow-up' + (atTurnLimit ? ' turn-boundary' : '')}>
        {atTurnLimit && (
          <div className="boundary-note" role="note">
            <strong>این گفت‌وگو به سه نوبت رسید.</strong>
            <span>پرسش بعدی شما به کادر «سؤال شما» منتقل و به‌صورت مستقل جست‌وجو می‌شود.</span>
          </div>
        )}
        <label htmlFor="follow-up">{atTurnLimit ? 'پرسش تازه' : 'سؤال بعدی'}</label>
        <p id="follow-up-hint" className="field-hint">
          Enter برای ارسال و Shift+Enter برای خط جدید.
        </p>
        <textarea
          id="follow-up"
          rows={3}
          value={followUp}
          onChange={(event) => setFollowUp(event.target.value)}
          onKeyDown={submitTextareaOnEnter}
          aria-describedby="follow-up-hint"
          placeholder={
            atTurnLimit
              ? 'پرسش بعدی را بنویسید تا در یک جست‌وجوی تازه باز شود.'
              : 'اگر بخشی از پاسخ روشن نبود، همین‌جا بپرسید.'
          }
        />
        <button type="submit" disabled={followUp.trim().length === 0 || jobRunning}>
          {atTurnLimit ? 'انتقال به پرسش تازه' : jobRunning ? 'در حال پاسخ…' : 'بپرس'}
        </button>
      </form>

      {error && (
        <p role="alert" className="job-error">
          {error}
        </p>
      )}
    </main>
  )
}

function Turn({ message, isAnswer }: { message: Message; isAnswer: boolean }) {
  if (message.role === 'user') {
    return <p className="user-text">{message.content}</p>
  }

  return (
    <>
      <Markdown>{message.content}</Markdown>
      <Citations citations={message.citations} images={message.images} />
      {isAnswer && message.citations.length === 0 && message.error_code && (
        // An answer with no citations is an abstention, and says so.
        <p className="abstention" role="note">
          این پاسخ بدون ارجاع به مستندات ارائه شده است، چون شواهد کافی پیدا نشد.
        </p>
      )}
    </>
  )
}
