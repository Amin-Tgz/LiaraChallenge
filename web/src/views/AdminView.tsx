/**
 * The operator's two questions: what are people complaining about, and what do
 * the numbers say.
 *
 * The admin API already existed and was reachable only with curl. This is the
 * face on it, and it adds no authentication of its own — the same HTTP Basic
 * guard the server has always used, with the credentials held in React state
 * and nowhere else. A reload asks again. That is the point: an administrator's
 * password does not get written to a browser's disk so that a page can skip a
 * login form.
 *
 * Every figure keeps the server's own no-data state. A metric that has recorded
 * nothing says so; it never renders as zero, because "no request has failed"
 * and "nothing has been measured" are opposite claims about a system.
 */

import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import type {
  AdminCredentials,
  DashboardPayload,
  FeedbackEntry,
  Metric,
} from '../api/admin'
import { fetchDashboard, fetchFeedback } from '../api/admin'

const WINDOW_DAYS = 30

const REASON_LABELS: Record<string, string> = {
  incorrect: 'نادرست',
  incomplete: 'ناقص',
  irrelevant: 'بی‌ربط',
  wrong_source: 'منبع اشتباه',
  other: 'سایر',
  unspecified: 'بدون علت',
}

const METRIC_LABELS: Record<string, string> = {
  chat_satisfaction_rate: 'رضایت از پاسخ‌های چت',
  faq_resolution_rate: 'نرخ حل‌شدن در مرحلهٔ FAQ',
  faq_hit_rate: 'نرخ نتیجه‌دار بودن جست‌وجوی FAQ',
  abstention_rate: 'نرخ امتناع از پاسخ',
  provider_fallbacks: 'جابه‌جایی به ارائه‌دهندهٔ دوم',
  token_usage: 'مصرف توکن',
  cost_usd: 'هزینه (دلار)',
  rescue_tool_split: 'سهم ابزارهای نجات',
  feedback_reasons: 'علت پاسخ‌های ردشده',
  top_questions: 'پرتکرارترین پرسش‌ها',
  top_cited_pages: 'پراستنادترین صفحات',
  lowest_rated_pages: 'صفحاتی با بیشترین بازخورد منفی',
  unresolved_questions: 'پرسش‌های بی‌پاسخ‌مانده',
  unresolved_pages: 'صفحات ناکافی در مرحلهٔ FAQ',
  questions_over_time: 'حجم پرسش در طول زمان',
  failures_by_code: 'خطاها بر اساس کد',
  active_index: 'ایندکس فعال',
  faq_corpus: 'وضعیت کورپوس FAQ',
}

/** Keys inside the object-valued metrics — the index and the FAQ corpus. */
const FIELD_LABELS: Record<string, string> = {
  index_version_id: 'شناسهٔ نسخهٔ ایندکس',
  status: 'وضعیت',
  source_commit: 'کامیت منبع',
  document_count: 'تعداد سند',
  chunk_count: 'تعداد قطعه',
  embedding_model: 'مدل امبدینگ',
  embedding_dimensions: 'ابعاد بردار',
  activated_at: 'زمان فعال‌سازی',
  created_at: 'زمان ساخت',
  total: 'کل',
  active: 'فعال',
  awaiting_reembedding: 'در انتظار امبدینگ دوباره',
  chat: 'چت',
  skill: 'Skill',
  mcp: 'MCP',
}

/** The order an operator reads them in: quality first, then demand, then health. */
const METRIC_ORDER = [
  'chat_satisfaction_rate',
  'faq_resolution_rate',
  'faq_hit_rate',
  'abstention_rate',
  'lowest_rated_pages',
  'feedback_reasons',
  'top_questions',
  'top_cited_pages',
  'unresolved_questions',
  'unresolved_pages',
  'questions_over_time',
  'rescue_tool_split',
  'failures_by_code',
  'provider_fallbacks',
  'token_usage',
  'cost_usd',
  'active_index',
  'faq_corpus',
]

export default function AdminView() {
  const [credentials, setCredentials] = useState<AdminCredentials | null>(null)

  if (!credentials) {
    return <AdminLogin onAuthenticated={setCredentials} />
  }
  return <AdminConsole credentials={credentials} onSignOut={() => setCredentials(null)} />
}

function AdminLogin({
  onAuthenticated,
}: {
  onAuthenticated: (credentials: AdminCredentials) => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    const candidate = { username, password }
    try {
      // The dashboard doubles as the credential check: there is no separate
      // login endpoint to keep in sync, and no session to invalidate.
      await fetchDashboard(candidate, WINDOW_DAYS)
      onAuthenticated(candidate)
    } catch (cause) {
      // Reported exactly as the server words it. It answers "wrong password",
      // "unknown user", and "admin not configured" identically on purpose.
      setError(
        cause instanceof ApiError ? cause.message : 'ارتباط با سرویس برقرار نشد.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="shell shell-narrow">
      <form className="state-card admin-login" onSubmit={submit}>
        <span className="eyebrow">دسترسی مدیر</span>
        <h1>ورود به کنسول</h1>
        <p className="lead">
          نام کاربری و رمز مدیر فقط در همین صفحه نگه داشته می‌شود و در مرورگر ذخیره
          نمی‌شود؛ با هر بارگذاری دوباره لازم است.
        </p>
        <label htmlFor="admin-username">نام کاربری</label>
        <input
          id="admin-username"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          required
        />
        <label htmlFor="admin-password">رمز عبور</label>
        <input
          id="admin-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
        <button type="submit" disabled={busy || !username || !password}>
          {busy ? 'در حال بررسی…' : 'ورود'}
        </button>
        {error && (
          <p role="alert" className="job-error">
            {error}
          </p>
        )}
      </form>
    </main>
  )
}

function AdminConsole({
  credentials,
  onSignOut,
}: {
  credentials: AdminCredentials
  onSignOut: () => void
}) {
  const [tab, setTab] = useState<'feedback' | 'metrics'>('feedback')
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null)
  const [feedback, setFeedback] = useState<FeedbackEntry[]>([])
  const [total, setTotal] = useState(0)
  const [outcome, setOutcome] = useState<'all' | 'resolved' | 'unresolved'>('unresolved')
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setError(null)
    try {
      const [metrics, page] = await Promise.all([
        fetchDashboard(credentials, WINDOW_DAYS),
        fetchFeedback(credentials, {
          windowDays: WINDOW_DAYS,
          outcome: outcome === 'all' ? undefined : outcome,
        }),
      ])
      setDashboard(metrics)
      setFeedback(page.items)
      setTotal(page.total)
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : 'ارتباط با سرویس برقرار نشد.',
      )
    }
  }, [credentials, outcome])

  useEffect(() => {
    void reload()
  }, [reload])

  return (
    <main className="shell admin-console">
      <header className="admin-header">
        <div>
          <span className="eyebrow">۳۰ روز گذشته</span>
          <h1>کنسول مدیر</h1>
        </div>
        <button type="button" className="ghost-button" onClick={onSignOut}>
          خروج
        </button>
      </header>

      <div className="admin-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'feedback'}
          className={tab === 'feedback' ? 'active' : undefined}
          onClick={() => setTab('feedback')}
        >
          بازخوردها
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'metrics'}
          className={tab === 'metrics' ? 'active' : undefined}
          onClick={() => setTab('metrics')}
        >
          آمار
        </button>
      </div>

      {error && (
        <p role="alert" className="job-error">
          {error}
        </p>
      )}

      {tab === 'feedback' ? (
        <section aria-label="بازخوردها">
          <div className="admin-filters">
            <label htmlFor="outcome-filter">نمایش</label>
            <select
              id="outcome-filter"
              value={outcome}
              onChange={(event) =>
                setOutcome(event.target.value as 'all' | 'resolved' | 'unresolved')
              }
            >
              <option value="unresolved">فقط ناموفق</option>
              <option value="resolved">فقط موفق</option>
              <option value="all">همه</option>
            </select>
            <span className="admin-count">{total} مورد</span>
          </div>

          {feedback.length === 0 ? (
            <p className="metric-empty">در این بازه بازخوردی ثبت نشده است.</p>
          ) : (
            <ul className="feedback-list">
              {feedback.map((entry) => (
                <li key={entry.id} className={`feedback-entry ${entry.outcome}`}>
                  <div className="feedback-entry-head">
                    <span className={`badge badge-${entry.outcome}`}>
                      {entry.outcome === 'resolved' ? 'کمک کرد' : 'کمک نکرد'}
                    </span>
                    <span className="badge">{entry.stage === 'chat' ? 'چت' : 'FAQ'}</span>
                    {entry.reason && (
                      <span className="badge badge-reason">
                        {REASON_LABELS[entry.reason] ?? entry.reason}
                      </span>
                    )}
                    <time dateTime={entry.created_at}>
                      {new Date(entry.created_at).toLocaleString('fa-IR')}
                    </time>
                  </div>
                  <p className="feedback-question">{entry.question}</p>
                  {entry.note && <p className="feedback-note-text">«{entry.note}»</p>}
                  {entry.answer && (
                    <details>
                      <summary>پاسخی که داده شده بود</summary>
                      <p className="feedback-answer">{entry.answer}</p>
                    </details>
                  )}
                  {entry.source_urls.length > 0 && (
                    <ul className="feedback-sources">
                      {entry.source_urls.map((url) => (
                        <li key={url}>
                          <a href={url} target="_blank" rel="noreferrer noopener">
                            {url}
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : (
        <section aria-label="آمار" className="metric-grid">
          {dashboard === null ? (
            <p role="status">در حال بارگذاری آمار…</p>
          ) : (
            METRIC_ORDER.filter((key) => key in dashboard.metrics).map((key) => (
              <MetricCard
                key={key}
                label={METRIC_LABELS[key] ?? key}
                metric={dashboard.metrics[key]}
              />
            ))
          )}
        </section>
      )}
    </main>
  )
}

function MetricCard({ label, metric }: { label: string; metric: Metric }) {
  return (
    <article className="metric-card">
      <h2>{label}</h2>
      {metric.no_data ? (
        // Never a zero. The server distinguishes "measured as none" from
        // "nothing recorded", and so does this.
        <p className="metric-empty">داده‌ای ثبت نشده است.</p>
      ) : (
        <>
          <MetricValue metric={metric} />
          <p className="metric-sample">از {metric.sample_size} رویداد</p>
        </>
      )}
    </article>
  )
}

function MetricValue({ metric }: { metric: Metric }) {
  const { value, unit } = metric

  if (unit === 'ratio' && typeof value === 'number') {
    return (
      <div className="metric-ratio">
        <strong>{Math.round(value * 100)}٪</strong>
        <div className="metric-bar" aria-hidden="true">
          <span style={{ width: `${Math.round(value * 100)}%` }} />
        </div>
      </div>
    )
  }

  if (Array.isArray(value)) {
    return (
      <ol className="metric-rows">
        {value.map((row, index) => (
          <li key={index}>
            <RowLabel row={row} />
            <span className="metric-row-count">{rowCount(row)}</span>
          </li>
        ))}
      </ol>
    )
  }

  if (value !== null && typeof value === 'object') {
    // Field rows read as a definition list: a short label and a value that can
    // be as long as an index id, so it is the value that gets to wrap.
    return (
      <ol className="metric-rows metric-rows-fields">
        {Object.entries(value as Record<string, unknown>).map(([key, entry]) => (
          <li key={key}>
            <span className="metric-row-label">
              {FIELD_LABELS[key] ?? REASON_LABELS[key] ?? key}
            </span>
            <span className="metric-row-count">{rowCount(entry)}</span>
          </li>
        ))}
      </ol>
    )
  }

  return <strong className="metric-scalar">{String(value)}</strong>
}

/**
 * A row's own label, and — when the row is about a documentation page — the
 * link to it.
 *
 * A cited page rendered as inert text is the one row an operator most wants to
 * open: the whole reason it is on the dashboard is to go and read it. The full
 * URL stays as the link's title while the visible text is just the path, so a
 * long address cannot shove the count out of the card.
 */
function RowLabel({ row }: { row: unknown }) {
  if (row === null || typeof row !== 'object') {
    return <span className="metric-row-label">{String(row)}</span>
  }

  const record = row as Record<string, unknown>
  const url = typeof record.source_url === 'string' ? record.source_url : null
  if (url) {
    return (
      <a
        className="metric-row-label metric-row-link"
        href={url}
        title={url}
        target="_blank"
        rel="noreferrer noopener"
      >
        {shortenUrl(url)}
      </a>
    )
  }

  const candidate = record.question ?? record.day ?? record.code
  return (
    <span className="metric-row-label">{String(candidate ?? JSON.stringify(row))}</span>
  )
}

/** `https://docs.liara.ir/paas/django/deploy` → `/paas/django/deploy`. */
function shortenUrl(url: string): string {
  try {
    const parsed = new URL(url)
    return decodeURIComponent(parsed.pathname + parsed.hash) || parsed.hostname
  } catch {
    // Not a URL we can parse — showing it whole beats showing nothing.
    return url
  }
}

function rowCount(row: unknown): string {
  if (typeof row === 'number') return String(row)
  if (row === null || typeof row !== 'object') return String(row)
  const record = row as Record<string, unknown>
  if (typeof record.count === 'number') return String(record.count)
  return JSON.stringify(row)
}
