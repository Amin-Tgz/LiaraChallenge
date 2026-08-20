/**
 * Related questions — deliberately not called "answers".
 *
 * These come from the FAQ fast path and are matched by similarity, so calling
 * them answers would promise more than the match justifies. The user judges
 * whether they helped, and that judgement is the product's most valuable
 * signal: an unresolved outcome names a real documentation gap.
 */

import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  fireAndForget,
  getSessionId,
  recordFeedback,
  recordInteraction,
} from '../api/client'
import type { FaqSearchResponse } from '../api/types'
import { Markdown } from '../components/Markdown'
import { recallQuestion, rememberQuestion } from '../flow'

type FlowState = { question?: string; results?: FaqSearchResponse }

export default function RelatedQuestionsView() {
  const navigate = useNavigate()
  const location = useLocation()
  const state = (location.state ?? {}) as FlowState

  const question = state.question ?? recallQuestion()
  const results = useMemo(() => state.results?.results ?? [], [state.results])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    if (question) rememberQuestion(question)
  }, [question])

  useEffect(() => {
    getSessionId()
      .then(({ session_id }) => setSessionId(session_id))
      .catch(() => setSessionId(null))
  }, [])

  useEffect(() => {
    if (!sessionId || !question || results.length === 0) return
    fireAndForget(
      recordInteraction({
        event_type: 'faq_impression',
        session_id: sessionId,
        question,
        faq_item_ids: results.map((result) => result.faq_item_id),
      }),
    )
  }, [sessionId, question, results])

  if (!question) {
    // Nothing to show and nothing to recover — say so and send them back.
    return (
      <main className="shell">
        <p role="alert">سؤالی برای نمایش پیدا نشد.</p>
        <button type="button" onClick={() => navigate('/')}>
          بازگشت به صفحه‌ی اول
        </button>
      </main>
    )
  }

  function toTools(outcome: 'resolved' | 'unresolved') {
    if (sessionId) {
      fireAndForget(
        recordFeedback({
          session_id: sessionId,
          question,
          outcome,
          presented_faq_ids: results.map((result) => result.faq_item_id),
        }),
      )
    }
    if (outcome === 'resolved') {
      navigate('/solved', { state: { question } })
      return
    }
    navigate('/tools', { state: { question } })
  }

  return (
    <main className="shell">
      <p className="original-question">
        <span className="label">سؤال شما:</span> {question}
      </p>

      {results.length === 0 ? (
        <section className="empty-state">
          <h1>پرسش مشابهی پیدا نشد</h1>
          {/* Distinct from "هیچ مستندی ایندکس نشده" — that is a system failure
              and arrives as its own error, not as this empty state. */}
          <p>
            مستندات جست‌وجو شدند، اما هیچ پرسش مرتبطی به سؤال شما نزدیک نبود.
            این یعنی احتمالاً مستندات این موضوع را پوشش نداده‌اند.
          </p>
          <button type="button" onClick={() => toTools('unresolved')}>
            سراغ ابزارهای نجات بروید
          </button>
        </section>
      ) : (
        <>
          <h1>پرسش‌های مرتبط</h1>
          <p className="lead">
            این‌ها پرسش‌هایی هستند که به سؤال شما نزدیک‌اند — نه لزوماً پاسخ
            دقیق آن.
          </p>

          <ul className="faq-list">
            {results.map((result) => {
              const open = expanded === result.faq_item_id
              return (
                <li key={result.faq_item_id}>
                  <button
                    type="button"
                    className="faq-question"
                    aria-expanded={open}
                    onClick={() => {
                      setExpanded(open ? null : result.faq_item_id)
                      if (!open && sessionId) {
                        fireAndForget(
                          recordInteraction({
                            event_type: 'faq_selection',
                            session_id: sessionId,
                            question,
                            faq_item_ids: [result.faq_item_id],
                          }),
                        )
                      }
                    }}
                  >
                    {result.question}
                  </button>
                  {open && (
                    <div className="faq-answer">
                      <Markdown>{result.answer}</Markdown>
                      <a
                        href={result.source_url}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        مشاهده در مستندات
                      </a>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>

          <div className="resolution">
            <p>آیا این‌ها مشکل شما را حل کرد؟</p>
            <button type="button" onClick={() => toTools('resolved')}>
              بله، حل شد
            </button>
            <button type="button" onClick={() => toTools('unresolved')}>
              نه، هنوز گیر کرده‌ام
            </button>
          </div>
        </>
      )}
    </main>
  )
}
