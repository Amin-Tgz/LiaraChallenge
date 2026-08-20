/**
 * Where a stuck user arrives.
 *
 * One multi-line field, because the questions this product exists for are
 * paragraphs — an error message and what was already tried — not search terms.
 * The question is sent to the FAQ fast path first; nothing generates an answer
 * at this stage.
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, listConversations, searchFaq } from '../api/client'
import type { ConversationSummary } from '../api/types'
import { rememberQuestion } from '../flow'

export default function LandingView() {
  const navigate = useNavigate()
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<ConversationSummary[]>([])

  useEffect(() => {
    // A reopened tab finds its previous conversations waiting.
    listConversations()
      .then(setHistory)
      .catch(() => setHistory([]))
  }, [])

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
        cause instanceof ApiError ? cause.message : 'ارتباط با سرویس برقرار نشد.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="shell">
      <h1>در مستندات لیارا گیر کرده‌اید؟</h1>
      <p className="lead">
        سؤالتان را کامل بنویسید — پیام خطا، کاری که انجام داده‌اید و نتیجه‌ای که
        انتظار داشتید. هرچه دقیق‌تر، پاسخ نزدیک‌تر.
      </p>

      <form onSubmit={submit}>
        <label htmlFor="question">سؤال شما</label>
        <textarea
          id="question"
          name="question"
          rows={6}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="مثلاً: هنگام استقرار برنامه‌ی Django با liara deploy خطای پورت می‌گیرم…"
          required
        />
        <button type="submit" disabled={busy || question.trim().length === 0}>
          {busy ? 'در حال جست‌وجو…' : 'پیدا کردن پاسخ'}
        </button>
      </form>

      {error && (
        <p role="alert" className="job-error">
          {error}
        </p>
      )}

      {history.length > 0 && (
        <section aria-labelledby="history-heading" className="history">
          <h2 id="history-heading">گفت‌وگوهای پیشین شما</h2>
          <ul>
            {history.map((conversation) => (
              <li key={conversation.id}>
                <a href={`/chat/${conversation.id}`}>
                  {conversation.title ?? conversation.initial_question}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  )
}
