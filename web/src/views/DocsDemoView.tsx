/**
 * A stand-in documentation page, built to hold the widget.
 *
 * The product's real target is not this site — it is the moment somebody is
 * reading Liara's documentation and does not find what they came for. This page
 * reproduces that moment so the rescue widget can be shown where it would
 * actually live.
 *
 * The content is invented. It is labelled as invented, prominently and
 * permanently, and every real answer links back to `docs.liara.ir`: a
 * convincing imitation of someone else's documentation is a liability, not a
 * better demo.
 */

import { RescueWidget } from '../components/RescueWidget'

const NAV = [
  {
    group: 'شروع کنید',
    items: ['معرفی لیارا', 'ساخت اولین برنامه', 'نصب CLI'],
  },
  {
    group: 'استقرار برنامه',
    items: ['Django', 'Laravel', 'Next.js', 'Docker'],
  },
  {
    group: 'دامنه و شبکه',
    items: ['افزودن دامنه', 'فعال‌سازی SSL', 'CDN'],
  },
  {
    group: 'پایگاه داده',
    items: ['PostgreSQL', 'MySQL', 'Redis'],
  },
]

const OUTLINE = [
  { id: 'demo-prereq', label: 'پیش‌نیازها' },
  { id: 'demo-config', label: 'فایل پیکربندی' },
  { id: 'demo-deploy', label: 'اجرای استقرار' },
  { id: 'demo-verify', label: 'بررسی نتیجه' },
]

export default function DocsDemoView() {
  return (
    <div className="docs-demo">
      <p className="demo-banner" role="note">
        <strong>صفحهٔ نمایشی.</strong> این صفحه بازسازی ظاهری مستندات لیارا برای
        نمایش ویجت نجات است و محتوایش واقعی نیست. مستندات رسمی در{' '}
        <a href="https://docs.liara.ir/" target="_blank" rel="noreferrer noopener">
          docs.liara.ir
        </a>{' '}
        است.
      </p>

      <div className="docs-demo-bar">
        <span className="docs-demo-brand">
          <img src="/images/logoLiara.png" alt="" aria-hidden="true" />
          مستندات
        </span>
        <span className="docs-demo-search" aria-hidden="true">
          جست‌وجو در مستندات…
        </span>
      </div>

      <div className="docs-demo-body">
        <nav className="docs-demo-nav" aria-label="فهرست مستندات نمایشی">
          {NAV.map((section) => (
            <div key={section.group}>
              <h2>{section.group}</h2>
              <ul>
                {section.items.map((item) => (
                  <li key={item} className={item === 'Django' ? 'current' : undefined}>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <article className="docs-demo-article">
          <p className="docs-demo-crumbs">استقرار برنامه ← Django</p>
          <h1>استقرار برنامهٔ Django</h1>
          <p>
            در این صفحهٔ نمونه، مراحل استقرار یک برنامهٔ Django روی پلتفرم توضیح داده
            می‌شود. متن زیر صرفاً برای نمایش چیدمان است.
          </p>

          <h2 id="demo-prereq">پیش‌نیازها</h2>
          <ul>
            <li>حساب کاربری فعال و CLI نصب‌شده</li>
            <li>فایل <code>requirements.txt</code> در ریشهٔ پروژه</li>
            <li>تنظیم <code>ALLOWED_HOSTS</code> برای دامنهٔ برنامه</li>
          </ul>

          <h2 id="demo-config">فایل پیکربندی</h2>
          <p>فایل زیر را در ریشهٔ پروژه بسازید:</p>
          <pre dir="ltr">
            <code>{`{
  "platform": "django",
  "app": "my-django-app",
  "port": 8000,
  "django": {
    "collectStatic": true,
    "migrate": true
  }
}`}</code>
          </pre>

          <h2 id="demo-deploy">اجرای استقرار</h2>
          <p>سپس دستور زیر را اجرا کنید:</p>
          <pre dir="ltr">
            <code>liara deploy --app my-django-app --port 8000</code>
          </pre>

          <h2 id="demo-verify">بررسی نتیجه</h2>
          <p>
            پس از پایان استقرار، لاگ‌ها را بررسی کنید و مطمئن شوید برنامه روی پورت
            اعلام‌شده پاسخ می‌دهد. اگر اینجا به مشکلی خوردید و جوابش را در این صفحه پیدا
            نکردید، ویجت پایین صفحه دقیقاً برای همان لحظه ساخته شده است.
          </p>
        </article>

        <aside className="docs-demo-outline" aria-label="در این صفحه">
          <h2>در این صفحه</h2>
          <ul>
            {OUTLINE.map((entry) => (
              <li key={entry.id}>
                <a href={`#${entry.id}`}>{entry.label}</a>
              </li>
            ))}
          </ul>
        </aside>
      </div>

      <RescueWidget />
    </div>
  )
}
