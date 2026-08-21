/**
 * "Is this what you were looking for?" — asked before spending a model call.
 *
 * These are matched by similarity, so they are offered as *related questions*
 * rather than as the answer. Two things follow from that, and both are load-
 * bearing:
 *
 * * The user decides. Nothing is generated until they say the FAQ did not help,
 *   which is the cheapest possible answer to a question the documentation
 *   already covers.
 * * Their decision is the product's best signal. "No" names a real gap, and it
 *   is recorded with the entries that were on screen when they said it.
 */

import { useState } from 'react'
import type { FaqResult } from '../api/types'
import { Markdown } from './Markdown'

type Props = {
  question: string
  results: FaqResult[]
  busy: boolean
  onResolved: () => void
  onUnresolved: () => void
}

export function FaqGate({ question, results, busy, onResolved, onUnresolved }: Props) {
  const [expanded, setExpanded] = useState<string | null>(results[0]?.faq_item_id ?? null)

  return (
    <section className="faq-gate" aria-label="پرسش‌های مرتبط">
      <p className="faq-gate-lead">
        میان پرسش‌های مستند، این‌ها به سؤال شما نزدیک بودند. اگر جوابتان این‌جاست،
        همین کافی است؛ وگرنه سؤال را به دستیار می‌سپاریم.
      </p>

      <ul className="faq-list">
        {results.map((result) => {
          const open = expanded === result.faq_item_id
          return (
            <li key={result.faq_item_id} className={open ? 'faq-card open' : 'faq-card'}>
              <button
                type="button"
                className="faq-question"
                aria-expanded={open}
                onClick={() => setExpanded(open ? null : result.faq_item_id)}
              >
                <span>{result.question}</span>
                <span className="faq-similarity" title="میزان نزدیکی به سؤال شما">
                  {Math.round(result.similarity * 100)}٪
                </span>
              </button>
              {open && (
                <div className="faq-answer">
                  <Markdown>{result.answer}</Markdown>
                  <a
                    className="faq-source"
                    href={result.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    منبع در مستندات لیارا
                    <ExternalIcon />
                  </a>
                </div>
              )}
            </li>
          )
        })}
      </ul>

      <div className="faq-gate-actions">
        <button type="button" className="ghost-button" onClick={onResolved} disabled={busy}>
          بله، جوابم را گرفتم
        </button>
        <button type="button" onClick={onUnresolved} disabled={busy}>
          {busy ? 'در حال آماده‌سازی گفت‌وگو…' : 'نه، از دستیار بپرس'}
        </button>
      </div>
      <p className="faq-gate-note">
        سؤال شما محفوظ است و در صورت ادامه، بدون بازنویسی به دستیار می‌رود:{' '}
        <span className="quoted-question">{question}</span>
      </p>
    </section>
  )
}

function ExternalIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M14 4h6v6M20 4l-8 8" />
      <path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </svg>
  )
}
