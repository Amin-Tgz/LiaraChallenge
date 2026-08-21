/**
 * What the assistant is actually doing while the user waits.
 *
 * Every line here comes from a step the agent really took — the tool it called,
 * the words it searched for, how many passages came back and how close the best
 * one was. None of it is simulated: a stage that did not happen produces no
 * line, because a progress display that invents reassuring steps is worse than
 * a spinner.
 *
 * It opens itself while work is running and collapses to a single summary line
 * once the answer arrives, since by then the answer is what matters.
 */

import { useEffect, useState } from 'react'
import type { TraceEvent } from '../api/types'

const TOOL_LABELS: Record<string, string> = {
  search_docs: 'جست‌وجو در مستندات',
  read_doc: 'خواندن یک صفحهٔ مستندات',
  search_related_questions: 'جست‌وجو میان پرسش‌های مستند',
}

type Props = {
  steps: TraceEvent[]
  /** True while the job is still running, which is when it opens itself. */
  running: boolean
}

export function ThinkingTrace({ steps, running }: Props) {
  const [open, setOpen] = useState(running)

  // Collapse when the work finishes, but never fight a user who opened it.
  useEffect(() => {
    if (running) setOpen(true)
  }, [running])

  if (steps.length === 0) return null

  return (
    <div className={'thinking-trace' + (running ? ' running' : '')}>
      <button
        type="button"
        className="trace-toggle"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <ChevronIcon />
        {running
          ? `در حال بررسی مستندات — ${steps.length} مرحله تا اینجا`
          : `${steps.length} مرحله جست‌وجو برای این پاسخ`}
      </button>

      {open && (
        <ol className="trace-steps">
          {steps.map((step) => (
            <li key={`${step.step}-${step.elapsed_ms}`} className={`trace-${step.status}`}>
              <span className="trace-tool">{TOOL_LABELS[step.tool] ?? step.tool}</span>
              {step.query && <span className="trace-query">«{step.query}»</span>}
              <span className="trace-outcome">
                {step.status === 'limit'
                  ? 'به سقف جست‌وجوی مجاز رسید'
                  : describeResult(step)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function describeResult(step: TraceEvent): string {
  if (step.result_count === null) return 'انجام شد'
  if (step.result_count === 0) return 'چیزی پیدا نشد'
  // Similarity is reported only when the tool measured it. "Not measured" and
  // "measured as zero" are different facts, so the absent case says less rather
  // than printing a number nobody computed.
  const closeness =
    step.top_similarity === null
      ? ''
      : ` — نزدیک‌ترین ${Math.round(step.top_similarity * 100)}٪`
  return `${step.result_count} نتیجه${closeness}`
}

function ChevronIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="chevron">
      <path d="m9 6 6 6-6 6" />
    </svg>
  )
}
