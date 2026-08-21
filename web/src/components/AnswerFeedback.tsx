/**
 * Was this answer any good?
 *
 * The verdict is the only thing sent. Which question it answered and which
 * documentation pages it leaned on are read server-side from the message
 * itself — that join is what turns a thumbs-down into "this page keeps
 * producing bad answers", which is the only form of this signal anyone can act
 * on.
 *
 * A rejection asks one follow-up, because "bad" is not actionable and
 * "incomplete" is: incomplete points at the corpus, irrelevant at retrieval,
 * incorrect at grounding.
 *
 * Submitting is fire-and-forget. A user who has just told us the answer was
 * wrong must not then be shown an error about their complaint.
 */

import { useState } from 'react'
import { fireAndForget, submitMessageFeedback } from '../api/client'
import type { FeedbackReason, MessageFeedback } from '../api/types'

const REASONS: { value: FeedbackReason; label: string }[] = [
  { value: 'incorrect', label: 'نادرست بود' },
  { value: 'incomplete', label: 'ناقص بود' },
  { value: 'irrelevant', label: 'به سؤالم ربط نداشت' },
  { value: 'wrong_source', label: 'منبعش اشتباه بود' },
]

type Props = {
  messageId: string
  existing: MessageFeedback | null
}

export function AnswerFeedback({ messageId, existing }: Props) {
  const [verdict, setVerdict] = useState<MessageFeedback | null>(existing)
  const [askingWhy, setAskingWhy] = useState(false)
  const [note, setNote] = useState('')

  function accept() {
    setVerdict({ outcome: 'resolved', reason: null })
    setAskingWhy(false)
    fireAndForget(submitMessageFeedback(messageId, { outcome: 'resolved' }))
  }

  function reject(reason: FeedbackReason) {
    setVerdict({ outcome: 'unresolved', reason })
    setAskingWhy(false)
    fireAndForget(
      submitMessageFeedback(messageId, {
        outcome: 'unresolved',
        reason,
        note: note.trim() || undefined,
      }),
    )
  }

  if (verdict) {
    return (
      <p className="answer-feedback recorded" role="status">
        {verdict.outcome === 'resolved'
          ? 'ممنون — ثبت شد که این پاسخ کمک کرد.'
          : 'ممنون — بازخورد شما ثبت شد و به بهترشدن مستندات کمک می‌کند.'}
      </p>
    )
  }

  return (
    <div className="answer-feedback">
      {!askingWhy ? (
        <div className="feedback-verdict">
          <span className="feedback-prompt">این پاسخ کمکتان کرد؟</span>
          <button
            type="button"
            className="icon-button feedback-yes"
            aria-label="بله، این پاسخ کمک کرد"
            onClick={accept}
          >
            <ThumbUpIcon />
          </button>
          <button
            type="button"
            className="icon-button feedback-no"
            aria-label="نه، این پاسخ کمک نکرد"
            onClick={() => setAskingWhy(true)}
          >
            <ThumbDownIcon />
          </button>
        </div>
      ) : (
        <div className="feedback-reasons">
          <span className="feedback-prompt">کجایش مشکل داشت؟</span>
          <div className="reason-buttons">
            {REASONS.map((reason) => (
              <button
                key={reason.value}
                type="button"
                className="ghost-button"
                onClick={() => reject(reason.value)}
              >
                {reason.label}
              </button>
            ))}
          </div>
          <label className="feedback-note-label" htmlFor={`note-${messageId}`}>
            توضیح بیشتر (اختیاری)
          </label>
          <textarea
            id={`note-${messageId}`}
            className="feedback-note"
            rows={2}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="مثلاً: دستور درست بود ولی مرحلهٔ تنظیم متغیر محیطی جا افتاده."
          />
          <button type="button" className="text-button" onClick={() => setAskingWhy(false)}>
            بی‌خیال
          </button>
        </div>
      )}
    </div>
  )
}

function ThumbUpIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 20V10l5-7 1 1v5h5a2 2 0 0 1 2 2.3l-1 6A2 2 0 0 1 17 19H7Z" />
      <path d="M7 10H4v10h3" />
    </svg>
  )
}

function ThumbDownIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M17 4v10l-5 7-1-1v-5H6a2 2 0 0 1-2-2.3l1-6A2 2 0 0 1 7 5h10Z" />
      <path d="M17 14h3V4h-3" />
    </svg>
  )
}
