/**
 * The conversation.
 *
 * State always comes from the server on mount, never from router state alone.
 * That is what makes a reload during generation restore the transcript and
 * rejoin the running job instead of starting a second one — the URL carries the
 * conversation id, and everything else is reconstructed from it.
 *
 * There is no longer a three-turn ceiling here. Turns that fall outside the
 * replayed window are summarized server-side, so a user simply keeps asking;
 * `HISTORY_LIMIT_REACHED` survives only as an abuse bound and is reported as
 * the ordinary, cause-naming error it now is.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import {
  ApiError,
  getConversation,
  newIdempotencyKey,
  sendMessage,
} from '../api/client'
import type { ConversationDetail, Job, Message } from '../api/types'
import { useJobStream } from '../api/useJobStream'
import { AnswerFeedback } from '../components/AnswerFeedback'
import { Citations } from '../components/Citations'
import { JobProgress } from '../components/JobProgress'
import { Markdown } from '../components/Markdown'
import { ThinkingTrace } from '../components/ThinkingTrace'
import { useAutoGrowingTextarea } from '../autogrow'
import { submitTextareaOnEnter } from '../keyboard'

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

export default function ChatView({
  onConversationsChanged,
}: {
  onConversationsChanged: () => void
}) {
  const { conversationId = '' } = useParams()
  const location = useLocation()
  const passed = (location.state ?? {}) as { jobId?: string }

  const [conversation, setConversation] = useState<ConversationDetail | null>(null)
  const [jobId, setJobId] = useState<string | null>(passed.jobId ?? null)
  const [followUp, setFollowUp] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const transcriptEnd = useRef<HTMLDivElement | null>(null)
  const followUpBox = useAutoGrowingTextarea(followUp)

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
    setConversation(null)
    setLoadError(null)
    setJobId(passed.jobId ?? null)
    void load()
    // `passed.jobId` is read once per navigation; re-running on its identity
    // would restart the stream every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load])

  // When a job finishes, the persisted transcript is the source of truth.
  useEffect(() => {
    if (stream.done) {
      void load().then(() => onConversationsChanged())
    }
  }, [stream.done, load, onConversationsChanged])

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [conversation?.messages.length, stream.answer, stream.trace.length])

  async function ask(event: React.FormEvent) {
    event.preventDefault()
    const text = followUp.trim()
    if (!text) return
    setError(null)
    try {
      const response = await sendMessage(conversationId, text, newIdempotencyKey())
      setFollowUp('')
      setJobId(response.job.id)
      await load()
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : 'ارتباط با سرویس برقرار نشد.',
      )
    }
  }

  if (loadError) {
    return (
      <main className="chat-surface">
        <div className="chat-scroll">
          <p role="alert" className="job-error">
            {loadError}
          </p>
        </div>
      </main>
    )
  }

  if (!conversation) {
    return (
      <main className="chat-surface">
        <div className="chat-scroll">
          <p role="status">در حال بازیابی گفت‌وگو…</p>
        </div>
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
  const jobRunning = jobId !== null && !stream.done

  return (
    <main className="chat-surface">
      <div className="chat-scroll">
        <p className="original-question">
          <span className="label">سؤال اصلی:</span> {conversation.initial_question}
        </p>

        <ol className="transcript">
          {conversation.messages.map((message) => (
            <li key={message.id} className={`turn turn-${message.role}`}>
              <Turn message={message} isAnswer={answered.has(message.id)} />
            </li>
          ))}

          {jobRunning && (
            <li className="turn turn-assistant">
              <ThinkingTrace steps={stream.trace} running />
              {streaming && <Markdown>{stream.answer}</Markdown>}
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

        {error && (
          <p role="alert" className="job-error">
            {error}
          </p>
        )}
      </div>

      <form onSubmit={ask} className="composer">
        <label className="visually-hidden" htmlFor="follow-up">
          سؤال بعدی
        </label>
        <div className="composer-box">
          <textarea
            id="follow-up"
            ref={followUpBox}
            rows={1}
            value={followUp}
            onChange={(event) => setFollowUp(event.target.value)}
            onKeyDown={submitTextareaOnEnter}
            aria-describedby="follow-up-hint"
            placeholder="اگر بخشی از پاسخ روشن نبود، همین‌جا بپرسید."
          />
          <button
            type="submit"
            className="send-button"
            disabled={followUp.trim().length === 0 || jobRunning}
            aria-label="ارسال سؤال بعدی"
          >
            <SendIcon />
          </button>
        </div>
        <p id="follow-up-hint" className="field-hint">
          Enter برای ارسال و Shift+Enter برای خط جدید.
        </p>
      </form>
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
      {isAnswer && <AnswerFeedback messageId={message.id} existing={message.feedback} />}
    </>
  )
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20 12 4 4l3 8-3 8 16-8Z" />
    </svg>
  )
}
