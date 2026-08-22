/**
 * A stand-in documentation page, built to hold the widget.
 *
 * The product's real target is not this site — it is the moment somebody is
 * reading Liara's documentation and does not find what they came for. This page
 * reproduces that moment so the rescue widget can be shown where it would
 * actually live, and it reproduces the *shape* of `docs.liara.ir` — right-hand
 * rail, centred command-palette search, gradient welcome card, quick-start and
 * product grids — because a widget only proves anything in the frame it will
 * really sit in.
 *
 * The content is invented. It is labelled as invented, prominently and
 * permanently, and every real answer links back to `docs.liara.ir`: a
 * convincing imitation of someone else's documentation is a liability, not a
 * better demo.
 */

import { RescueWidget } from '../components/RescueWidget'

type NavItem = { label: string; icon: IconName; current?: boolean }
type NavGroup = { chip?: string; items: NavItem[] }

const NAV: NavGroup[] = [
  {
    items: [
      { label: 'خانه', icon: 'home', current: true },
      { label: 'لیارا در یک نگاه', icon: 'sparkle' },
    ],
  },
  {
    chip: 'محصولات',
    items: [
      { label: 'پلتفرم', icon: 'rocket' },
      { label: 'هوش مصنوعی', icon: 'sparkle' },
      { label: 'سرور مجازی ابری (VPS)', icon: 'cloud' },
      { label: 'دیتابیس', icon: 'database' },
      { label: 'برنامه‌های آماده', icon: 'rocket' },
      { label: 'ایمیل', icon: 'mail' },
      { label: 'ذخیره‌سازی ابری', icon: 'clip' },
      { label: 'سامانه مدیریت دامنه', icon: 'globe' },
    ],
  },
  {
    chip: 'ارجاعات',
    items: [
      { label: 'Liara CLI', icon: 'terminal' },
      { label: 'Liara API', icon: 'code' },
      { label: 'پنل کاربری لیارا', icon: 'user' },
      { label: 'تیم‌ها و دسترسی‌ها', icon: 'users' },
      { label: 'مخازن نرم‌افزاری (میرورها)', icon: 'book' },
    ],
  },
  {
    items: [
      { label: 'SLAs', icon: 'shield' },
      { label: 'تلویزیون لیارا', icon: 'play' },
      { label: 'صفحه وضعیت (Status Page)', icon: 'gauge' },
    ],
  },
]

/** The quick-start row: a framework mark, a label, and a direction arrow. */
const QUICKSTART = [
  { name: 'NextJS', mark: 'N', tint: '#111827' },
  { name: 'Laravel', mark: 'L', tint: '#ef4444' },
  { name: 'Django', mark: 'dj', tint: '#0c4b33' },
  { name: 'NodeJS', mark: 'JS', tint: '#3c873a' },
  { name: 'React', mark: 'R', tint: '#149eca' },
  { name: 'Vue', mark: 'V', tint: '#41b883' },
  { name: 'Docker', mark: 'D', tint: '#1d63ed' },
  { name: '.NET', mark: '.N', tint: '#5c2d91' },
]

const PRODUCTS: { title: string; body: string; icon: IconName }[] = [
  {
    title: 'پلتفرم (PaaS)',
    body: 'بررسی انواع پلتفرم‌های پشتیبانی‌شده در لیارا و آموزش گام‌به‌گام راه‌اندازی و استقرار اپلیکیشن‌ها در هر کدام از این پلتفرم‌ها',
    icon: 'rocket',
  },
  {
    title: 'هوش مصنوعی (AI API)',
    body: 'شامل معرفی API‌های مرتبط با هوش مصنوعی، نحوه اتصال آن‌ها به پروژه‌ها، و نحوه استفاده از آن‌ها در بستر لیارا',
    icon: 'sparkle',
  },
  {
    title: 'سرور مجازی ابری (IaaS)',
    body: 'اطلاعات مربوط به سرورهای مجازی ابری و نحوه راه‌اندازی آن‌ها در لیارا',
    icon: 'cloud',
  },
  {
    title: 'دیتابیس (DBaaS)',
    body: 'اطلاعات مربوط به دیتابیس‌ها و استفاده اصولی از آن‌ها',
    icon: 'database',
  },
  {
    title: 'برنامه‌های آماده',
    body: 'اطلاعات در مورد شخصی‌سازی و نحوه کار با برنامه‌هایی که فقط با یک کلیک، در لیارا به شما تحویل داده می‌شوند',
    icon: 'clip',
  },
  {
    title: 'ایمیل',
    body: 'اطلاعات مربوط به سرویس ایمیل لیارا، نحوه راه‌اندازی، اتصال برنامه به ایمیل سرور و مدیریت ایمیل‌ها',
    icon: 'mail',
  },
  {
    title: 'ذخیره‌سازی ابری (Object Storage)',
    body: 'جزئیات دقیق مربوط به سرویس ذخیره‌سازی ابری لیارا، نحوه استفاده از آن و مدیریت باکت‌ها',
    icon: 'clip',
  },
  {
    title: 'سامانه مدیریت دامنه (DNS)',
    body: 'اطلاعات مربوط به مدیریت دامنه، رکوردها و اتصال دامنه به برنامه‌های مستقرشده',
    icon: 'globe',
  },
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

      <header className="docs-demo-bar">
        <span className="docs-demo-brand">
          <img src="/images/logoLiara.png" alt="" aria-hidden="true" />
          <span className="docs-demo-chip">مستندات</span>
        </span>

        <span className="docs-demo-search" aria-hidden="true">
          <Icon name="search" />
          <span className="docs-demo-search-text">جستجو کنید</span>
          <kbd>⌘ K</kbd>
        </span>

        <span className="docs-demo-actions" aria-hidden="true">
          <span className="docs-demo-icon-slot">
            <Icon name="sun" />
          </span>
          <span className="docs-demo-panel-button">ورود به پنل کاربری</span>
        </span>
      </header>

      <div className="docs-demo-body">
        <nav className="docs-demo-nav" aria-label="فهرست مستندات نمایشی">
          {NAV.map((group, index) => (
            <div key={group.chip ?? index} className="docs-demo-nav-group">
              {group.chip && <span className="docs-demo-nav-chip">{group.chip}</span>}
              <ul>
                {group.items.map((item) => (
                  <li key={item.label} className={item.current ? 'current' : undefined}>
                    <Icon name={item.icon} />
                    <span>{item.label}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <main className="docs-demo-main">
          <section className="docs-welcome docs-demo-hero">
            <div className="docs-window" aria-hidden="true">
              <div className="docs-window-bar">
                <i />
                <i />
                <i />
              </div>
              <span>docs.liara.ir</span>
              <strong>Documentation.</strong>
            </div>
            <div className="welcome-copy">
              <h1>به مستندات لیارا خوش‌آمدید&nbsp;👋</h1>
              <p>اینجا خانه‌ی توسعه‌دهندگان است. خانه‌ی خودتان. راحت باشید.</p>
            </div>
          </section>

          <h2 className="docs-demo-section-title">همین حالا استقرار را شروع کنید</h2>
          <ul className="docs-demo-quickstart">
            {QUICKSTART.map((entry) => (
              <li key={entry.name}>
                <span className="docs-demo-mark" style={{ background: entry.tint }}>
                  {entry.mark}
                </span>
                <span className="docs-demo-quickstart-label">
                  {/* The framework name is Latin inside Persian: bdi keeps a
                      leading dot on ".NET" from drifting to the far side. */}
                  شروع به کار با <bdi>{entry.name}</bdi>
                </span>
                <span className="docs-demo-arrow" aria-hidden="true">
                  ←
                </span>
              </li>
            ))}
          </ul>

          <h2 className="docs-demo-section-title">محصولات لیارا</h2>
          <ul className="docs-demo-products">
            {PRODUCTS.map((product) => (
              <li key={product.title}>
                <span className="docs-demo-product-icon">
                  <Icon name={product.icon} />
                </span>
                <h3>{product.title}</h3>
                <p>{product.body}</p>
                <span className="docs-demo-more">بیشتر بدانید</span>
              </li>
            ))}
          </ul>
        </main>
      </div>

      <RescueWidget />
    </div>
  )
}

type IconName =
  | 'home'
  | 'sparkle'
  | 'rocket'
  | 'cloud'
  | 'database'
  | 'mail'
  | 'clip'
  | 'globe'
  | 'terminal'
  | 'code'
  | 'user'
  | 'users'
  | 'book'
  | 'shield'
  | 'play'
  | 'gauge'
  | 'search'
  | 'sun'

/** Line icons, drawn on one 24-grid so every row in the rail lines up. */
const PATHS: Record<IconName, string> = {
  home: 'M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1Z',
  sparkle: 'M12 3v6m0 6v6m-6-9h6m6 0h-6M6.5 6.5l3 3m5 5 3 3m0-11-3 3m-5 5-3 3',
  rocket: 'M5 19c0-3 1-5 3-5m3-11c4 0 8 4 8 8 0 4-4 8-8 8-1-2-3-4-5-5 0-4 1-11 5-11Zm1 7h.01',
  cloud: 'M7 18h10a4 4 0 0 0 .2-8A6 6 0 0 0 5.5 11 3.5 3.5 0 0 0 7 18Z',
  database:
    'M4 6c0-1.1 3.6-2 8-2s8 .9 8 2-3.6 2-8 2-8-.9-8-2Zm0 0v12c0 1.1 3.6 2 8 2s8-.9 8-2V6m-16 6c0 1.1 3.6 2 8 2s8-.9 8-2',
  mail: 'M3 6h18v12H3Zm0 0 9 7 9-7',
  clip: 'M17 8v9a5 5 0 0 1-10 0V7a3 3 0 0 1 6 0v9a1 1 0 0 1-2 0V8',
  globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 0c-3 3-3 15 0 18m0-18c3 3 3 15 0 18M3.5 9h17m-17 6h17',
  terminal: 'M5 5h14v14H5Zm3 4 3 3-3 3m5 0h4',
  code: 'm8 7-5 5 5 5m8-10 5 5-5 5',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0',
  users: 'M9 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0m2-8a4 4 0 0 0 0-8m5 16a7 7 0 0 0-4-6',
  book: 'M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 0-3 3Zm14 0h-2v16h2Z',
  shield: 'M12 3 5 6v6c0 4 3 7 7 9 4-2 7-5 7-9V6Zm-3 9 2 2 4-4',
  play: 'M4 5h16v12H4Zm6 3 5 3-5 3Zm-2 13h8',
  gauge: 'M4 18a8 8 0 1 1 16 0Zm8-3 3.5-4',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 4 4',
  sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-6v2m0 16v2M4 12H2m20 0h-2M5.6 5.6 4.2 4.2m15.6 15.6-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4',
}

function Icon({ name }: { name: IconName }) {
  return (
    <svg className="docs-demo-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  )
}
