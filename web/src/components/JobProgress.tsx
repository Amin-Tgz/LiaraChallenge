/**
 * What is happening to the user's question, in plain Persian.
 *
 * Every state says something concrete. A failure in particular names its own
 * cause and comes from the server's error taxonomy — the UI never substitutes a
 * generic "مشکلی پیش آمد", because that hides an outage behind something that
 * looks like a normal answer.
 */

import { useEffect, useState } from 'react'
import type { JobStatus } from '../api/types'

const THINKING_FRAMES = [
  '/images/think1.png',
  '/images/think2.png',
  '/images/think3.png',
  '/images/think4.png',
]

const LABELS: Record<JobStatus, string> = {
  queued: 'سؤال شما ثبت شد و در نوبت پاسخ‌گویی است.',
  retrieving: 'در حال جست‌وجو در مستندات لیارا…',
  generating: 'در حال نوشتن پاسخ بر پایه‌ی مستندات…',
  retrying: 'پاسخ‌گویی در تلاش اول ناموفق بود و دوباره تلاش می‌کنم…',
  completed: 'پاسخ آماده است.',
  failed: 'پاسخ‌گویی ناتمام ماند.',
}

type Props = {
  status: JobStatus
  attempt?: number
  maxAttempts?: number
  errorCode?: string | null
  errorMessage?: string | null
}

export function JobProgress({
  status,
  attempt,
  maxAttempts,
  errorCode,
  errorMessage,
}: Props) {
  const failed = status === 'failed'
  const busy =
    status === 'queued' ||
    status === 'retrieving' ||
    status === 'generating' ||
    status === 'retrying'

  return (
    <div
      className={`job-progress job-${status}`}
      role="status"
      aria-live="polite"
      aria-busy={busy}
    >
      {busy && <ThinkingFrames />}
      <p className="job-label">
        {LABELS[status]}
      </p>

      {status === 'retrying' && attempt !== undefined && maxAttempts !== undefined && (
        <p className="job-detail">
          تلاش {attempt} از {maxAttempts}
        </p>
      )}

      {failed && (
        <p className="job-detail job-error" role="alert">
          {/* The cause, not a placeholder. */}
          {errorMessage ?? 'علت خطا از سرویس دریافت نشد.'}
          {errorCode && <code className="error-code"> ({errorCode})</code>}
        </p>
      )}
    </div>
  )
}

function ThinkingFrames() {
  const [frame, setFrame] = useState(0)

  useEffect(() => {
    const timer = window.setInterval(() => {
      setFrame((current) => (current + 1) % THINKING_FRAMES.length)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <div className="thinking-visual" aria-hidden="true">
      <img
        src={THINKING_FRAMES[frame]}
        alt=""
        data-testid="thinking-frame"
        decoding="async"
      />
    </div>
  )
}
