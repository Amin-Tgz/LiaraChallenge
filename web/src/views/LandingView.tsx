import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, listConversations, searchFaq } from '../api/client'
import type { ConversationSummary } from '../api/types'
import {
  forgetNextQuestion,
  recallNextQuestion,
  rememberQuestion,
} from '../flow'
import { submitTextareaOnEnter } from '../keyboard'

export default function LandingView() {
  const navigate = useNavigate()
  const carriedDraft = recallNextQuestion()
  const [question, setQuestion] = useState(carriedDraft)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<ConversationSummary[]>([])

  useEffect(() => {
    if (carriedDraft) forgetNextQuestion()
    listConversations().then(setHistory).catch(() => setHistory([]))
  }, [carriedDraft])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const text = question.trim()
    if (!text || busy) return

    setBusy(true)
    setError(null)
    try {
      const results = await searchFaq(text)
      rememberQuestion(text)
      navigate('/related', { state: { question: text, results } })
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : 'ارتباط با سرویس برقرار نشد. اتصال شبکه را بررسی کنید.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="shell landing-shell">
      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">راهنمای مبتنی بر مستندات رسمی</span>
          <h1>وقتی در مستندات لیارا گیر می‌کنید، مسیر بعدی را پیدا کنید.</h1>
          <p className="lead">
            خطا، کاری که انجام داده‌اید و نتیجهٔ مورد انتظار را بنویسید. ابتدا میان
            پرسش‌های مستند جست‌وجو می‌کنیم؛ اگر کافی نبود، ابزارهای نجات آماده‌اند.
          </p>
          <ul className="trust-list" aria-label="ویژگی‌های پاسخ">
            <li><CheckIcon /> ارجاع مستقیم به مستندات</li>
            <li><CheckIcon /> پرهیز از پاسخ بدون شاهد</li>
            <li><CheckIcon /> حفظ پرسش در تمام مسیر</li>
          </ul>
        </div>

        <form onSubmit={submit} className="question-card">
          {carriedDraft && (
            <p className="handoff-note" role="status">
              این پرسش از گفت‌وگوی قبلی به یک جست‌وجوی تازه منتقل شد.
            </p>
          )}
          <label htmlFor="question">سؤال شما</label>
          <p id="question-hint" className="field-hint">
            پیام خطا را عیناً وارد کنید. Enter برای جست‌وجو و Shift+Enter برای خط جدید.
          </p>
          <textarea
            id="question"
            name="question"
            rows={7}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={submitTextareaOnEnter}
            aria-describedby="question-hint"
            placeholder="مثلاً: هنگام استقرار برنامهٔ Django با liara deploy خطای پورت می‌گیرم…"
            autoFocus={Boolean(carriedDraft)}
            required
          />
          <div className="form-footer">
            <span className="keyboard-hint" aria-hidden="true">Enter ↵</span>
            <button type="submit" disabled={busy || question.trim().length === 0}>
              {busy ? 'در حال جست‌وجو…' : 'پیدا کردن پاسخ'}
              {!busy && <ArrowIcon />}
            </button>
          </div>
          {error && <p role="alert" className="job-error">{error}</p>}
        </form>
      </section>

      <section className="path-strip" aria-label="مسیر پاسخ‌گویی">
        <div><span>۱</span><strong>جست‌وجوی سریع</strong><small>میان پرسش‌های مستند</small></div>
        <div><span>۲</span><strong>بررسی منبع</strong><small>با لینک و بخش دقیق</small></div>
        <div><span>۳</span><strong>ابزار نجات</strong><small>گفت‌وگو، Skill یا MCP</small></div>
      </section>

      {history.length > 0 && (
        <section aria-labelledby="history-heading" className="history section-block">
          <div className="section-heading">
            <div>
              <span className="eyebrow">ادامه از جایی که بودید</span>
              <h2 id="history-heading">گفت‌وگوهای پیشین شما</h2>
            </div>
          </div>
          <ul className="history-grid">
            {history.map((conversation) => (
              <li key={conversation.id}>
                <Link to={'/chat/' + conversation.id}>
                  <span>{conversation.title ?? conversation.initial_question}</span>
                  <small>{conversation.message_count} پیام</small>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m5 12 4 4L19 6" />
    </svg>
  )
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M19 12H5M11 18l-6-6 6-6" />
    </svg>
  )
}
