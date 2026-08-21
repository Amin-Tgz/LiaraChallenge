/**
 * The entry point as it would appear inside the real documentation.
 *
 * This is the whole argument of the demo page: someone reading a Liara docs
 * page who has not found their answer should not have to know this assistant
 * exists — it should be sitting in the corner of the page they are already
 * stuck on.
 *
 * Hover or focus reveals the deer, which is the one place that image belongs:
 * it names the feeling of being stuck, and it names it at the moment somebody
 * is feeling it.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export function RescueWidget() {
  const navigate = useNavigate()
  const [revealed, setRevealed] = useState(false)

  return (
    <div
      className="rescue-widget"
      onMouseEnter={() => setRevealed(true)}
      onMouseLeave={() => setRevealed(false)}
    >
      <div
        className={'rescue-peek' + (revealed ? ' revealed' : '')}
        // Decorative reinforcement of the button's own label, so a screen
        // reader hears the invitation once rather than twice.
        aria-hidden="true"
      >
        <img src="/images/stopped.png" alt="" decoding="async" loading="lazy" />
        <p>
          <strong>مثل آهو توی برف گیر کردی؟</strong>
          <span>سؤالت را بنویس؛ راه خروج را از دل مستندات پیدا می‌کنیم.</span>
        </p>
      </div>

      <button
        type="button"
        className="rescue-bubble"
        onFocus={() => setRevealed(true)}
        onBlur={() => setRevealed(false)}
        onClick={() => navigate('/')}
        aria-label="جوابت را پیدا نکردی؟ دستیار نجات مستندات لیارا را باز کن"
      >
        <span className="rescue-bubble-text">
          جوابت رو
          <br />
          پیدا نکردی؟
          <br />
          بیا اینجا
        </span>
      </button>
    </div>
  )
}
