/**
 * The first screen, which is now the conversation itself.
 *
 * The rescue flow used to spend three navigations getting to an answer: a form,
 * a related-questions page, a tool-choice page, then the chat. Every one of
 * those was a place to lose someone who was already stuck. The whole path now
 * happens here without changing route — ask, see whether the documentation
 * already answers it, and continue into chat only if it does not.
 *
 * The one model call is still gated behind the user's own judgement: nothing is
 * generated until they say the FAQ did not help.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ApiError,
  fireAndForget,
  getSessionId,
  newIdempotencyKey,
  recordFeedback,
  recordInteraction,
  searchFaq,
  startConversation,
} from '../api/client'
import type { FaqResult } from '../api/types'
import { FaqGate } from '../components/FaqGate'
import { useAutoGrowingTextarea } from '../autogrow'
import { submitTextareaOnEnter } from '../keyboard'

/** Concrete enough to be worth clicking, and all answerable from the corpus. */
const EXAMPLES = [
  'چطور یک برنامهٔ Django را روی لیارا مستقر کنم؟',
  'برای دامنهٔ اختصاصی چه رکوردی باید بسازم و SSL چطور فعال می‌شود؟',
  'لاگ‌های برنامه‌ام را از چه راهی ببینم؟',
]

type Stage =
  | { kind: 'idle' }
  | { kind: 'searching'; question: string }
  | { kind: 'gate'; question: string; results: FaqResult[] }
  | { kind: 'resolved' }

export default function LandingView({ onConversationsChanged }: { onConversationsChanged: () => void }) {
  const navigate = useNavigate()
  const [question, setQuestion] = useState('')
  const [stage, setStage] = useState<Stage>({ kind: 'idle' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const questionBox = useAutoGrowingTextarea(question)

  function fail(cause: unknown) {
    setError(
      cause instanceof ApiError
        ? cause.message
        : 'ارتباط با سرویس برقرار نشد. اتصال شبکه را بررسی کنید.',
    )
  }

  /** Hand the question to the assistant and follow it into the conversation. */
  async function toChat(text: string, presentedFaqIds: string[]) {
    setBusy(true)
    setError(null)
    try {
      // Telemetry rides alongside; it is never allowed to hold up the answer.
      void getSessionId()
        .then(({ session_id }) => {
          if (presentedFaqIds.length > 0) {
            fireAndForget(
              recordFeedback({
                session_id,
                question: text,
                outcome: 'unresolved',
                presented_faq_ids: presentedFaqIds,
              }),
            )
          }
          fireAndForget(
            recordInteraction({
              event_type: 'rescue_tool_transition',
              session_id,
              question: text,
              rescue_tool: 'chat',
            }),
          )
        })
        .catch(() => undefined)

      const response = await startConversation(text, newIdempotencyKey())
      onConversationsChanged()
      navigate('/chat/' + response.conversation_id, {
        state: { jobId: response.job.id },
      })
    } catch (cause) {
      fail(cause)
    } finally {
      setBusy(false)
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const text = question.trim()
    if (!text || busy) return

    setBusy(true)
    setError(null)
    setStage({ kind: 'searching', question: text })
    try {
      const found = await searchFaq(text)
      if (found.results.length === 0) {
        // Nothing to offer and nothing to ask about — going straight to the
        // assistant is the only useful thing left to do.
        setStage({ kind: 'idle' })
        setQuestion('')
        await toChat(text, [])
        return
      }
      setStage({ kind: 'gate', question: text, results: found.results })
      setQuestion('')
      void getSessionId()
        .then(({ session_id }) =>
          fireAndForget(
            recordInteraction({
              event_type: 'faq_impression',
              session_id,
              question: text,
              faq_item_ids: found.results.map((result) => result.faq_item_id),
            }),
          ),
        )
        .catch(() => undefined)
    } catch (cause) {
      setStage({ kind: 'idle' })
      fail(cause)
    } finally {
      setBusy(false)
    }
  }

  function markResolved(text: string, results: FaqResult[]) {
    void getSessionId()
      .then(({ session_id }) =>
        fireAndForget(
          recordFeedback({
            session_id,
            question: text,
            outcome: 'resolved',
            presented_faq_ids: results.map((result) => result.faq_item_id),
          }),
        ),
      )
      .catch(() => undefined)
    setStage({ kind: 'resolved' })
  }

  const asked = stage.kind === 'searching' || stage.kind === 'gate' ? stage.question : null

  // On the empty first screen the composer belongs in the middle of the page,
  // with the intro above it — that is the one thing the visitor is here to do.
  // Once a question is in flight it drops to its usual place at the foot of the
  // transcript, where every following turn will be typed.
  const composer = (
    <form onSubmit={submit} className="composer">
      <label className="visually-hidden" htmlFor="question">
        سؤال شما
      </label>
      <div className="composer-box">
        <textarea
          id="question"
          name="question"
          ref={questionBox}
          rows={1}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={submitTextareaOnEnter}
          aria-describedby="question-hint"
          placeholder="مثلاً: هنگام استقرار برنامهٔ Django با liara deploy خطای پورت می‌گیرم…"
          required
        />
        <button
          type="submit"
          className="send-button"
          disabled={busy || question.trim().length === 0}
          aria-label="ارسال سؤال"
        >
          <SendIcon />
        </button>
      </div>
      <p id="question-hint" className="field-hint">
        Enter برای ارسال و Shift+Enter برای خط جدید.
      </p>
    </form>
  )

  return (
    <main className="chat-surface">
      <div className="chat-scroll">
        {stage.kind === 'idle' && (
          <section className="composer-intro">
            <div className="docs-welcome">
              <div className="docs-window" aria-hidden="true">
                <div className="docs-window-bar"><i /><i /><i /></div>
                <span>docs.liara.ir</span>
                <strong>Documentation.</strong>
              </div>
              <div className="welcome-copy">
                <span className="welcome-wave">👋 خوش آمدید</span>
                <h1>دستیار لیارا</h1>
                <p>هر جا در مستندات گیر کردید، مسئله را همین‌جا با ما در میان بگذارید.</p>
              </div>
            </div>
            <div className="ask-intro">
              <span className="eyebrow">✨ جست‌وجوی هوشمند در مستندات</span>
              <h2>غمت نباشه، خودم برات درستش می‌کنم</h2>
              <p className="lead">
                سؤالت از لیارا چیه؟ بگو من حلش می‌کنم؛ ابتدا پاسخ‌های مرتبط را پیدا
                می‌کنیم و اگر کافی نبود، گفتگو را ادامه می‌دهیم.
              </p>
            </div>
            <div className="composer-centred">{composer}</div>
            <ul className="example-questions" aria-label="نمونهٔ پرسش‌ها">
              {EXAMPLES.map((example) => (
                <li key={example}>
                  <button type="button" onClick={() => setQuestion(example)}>
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {asked && (
          <div className="turn turn-user standalone-turn">
            <p className="user-text">{asked}</p>
          </div>
        )}

        {stage.kind === 'searching' && (
          <p className="searching-note" role="status">
            در حال جست‌وجو میان پرسش‌های مستند…
          </p>
        )}

        {stage.kind === 'gate' && (
          <FaqGate
            question={stage.question}
            results={stage.results}
            busy={busy}
            onResolved={() => markResolved(stage.question, stage.results)}
            onUnresolved={() =>
              void toChat(
                stage.question,
                stage.results.map((result) => result.faq_item_id),
              )
            }
          />
        )}

        {stage.kind === 'resolved' && (
          <section className="state-card success-card">
            <span className="eyebrow">بازخورد ثبت شد</span>
            <h1>خوشحالیم که مشکل حل شد</h1>
            <p className="lead">
              بازخورد شما ترتیب پرسش‌های مرتبط را بهتر می‌کند و شکاف‌های مستندات را
              آشکار می‌سازد.
            </p>
            <button type="button" onClick={() => setStage({ kind: 'idle' })}>
              پرسش تازه
            </button>
          </section>
        )}

        {error && (
          <p role="alert" className="job-error">
            {error}
          </p>
        )}
      </div>

      {stage.kind === 'searching' && composer}
    </main>
  )
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20 12 4 4l3 8-3 8 16-8Z" />
    </svg>
  )
}
