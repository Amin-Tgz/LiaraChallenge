import { useEffect, useState } from 'react'
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom'
import ChatView from './views/ChatView'
import LandingView from './views/LandingView'
import RelatedQuestionsView from './views/RelatedQuestionsView'
import RescueToolsView from './views/RescueToolsView'
import ToolGuideView from './views/ToolGuideView'

type Theme = 'light' | 'dark'
const THEME_KEY = 'rescue.theme'

function preferredTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    // Storage may be unavailable; the system preference is still usable.
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(preferredTheme)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    try {
      localStorage.setItem(THEME_KEY, theme)
    } catch {
      // The visible theme still works for this page load.
    }
  }, [theme])

  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      className="icon-button"
      aria-label={next === 'dark' ? 'فعال‌کردن حالت تیره' : 'فعال‌کردن حالت روشن'}
      title={next === 'dark' ? 'حالت تیره' : 'حالت روشن'}
      onClick={() => setTheme(next)}
    >
      {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
    </button>
  )
}

function AppHeader() {
  const location = useLocation()
  return (
    <header className="masthead">
      <div className="masthead-inner">
        <Link className="brand" to="/" aria-label="دستیار نجات مستندات لیارا؛ صفحهٔ اصلی">
          <span className="brand-mark" aria-hidden="true">L</span>
          <span>
            <strong>نجات مستندات لیارا</strong>
            <small>پاسخ مستند، بدون حدس</small>
          </span>
        </Link>
        <nav className="header-actions" aria-label="ابزارهای صفحه">
          {location.pathname !== '/' && (
            <Link className="icon-button" to="/" aria-label="بازگشت به صفحهٔ اصلی" title="خانه">
              <HomeIcon />
            </Link>
          )}
          <ThemeToggle />
        </nav>
      </div>
    </header>
  )
}

function SolvedView() {
  const navigate = useNavigate()
  return (
    <main className="shell shell-narrow">
      <section className="state-card success-card">
        <span className="eyebrow">بازخورد ثبت شد</span>
        <h1>خوشحالیم که مشکل حل شد</h1>
        <p className="lead">
          بازخورد شما به بهترشدن ترتیب پرسش‌های مرتبط و آشکارشدن شکاف‌های مستندات کمک می‌کند.
        </p>
        <button type="button" onClick={() => navigate('/')}>پرسش تازه</button>
      </section>
    </main>
  )
}

function NotFound() {
  return (
    <main className="shell shell-narrow">
      <section className="state-card">
        <span className="eyebrow">خطای ۴۰۴</span>
        <h1>این صفحه پیدا نشد</h1>
        <p className="lead">نشانی واردشده به هیچ بخش فعالی از دستیار اشاره نمی‌کند.</p>
        <Link className="button-link" to="/">بازگشت به صفحهٔ اصلی</Link>
      </section>
    </main>
  )
}

function AppFrame() {
  return (
    <>
      <a className="skip-link" href="#main-content">پرش به محتوای اصلی</a>
      <AppHeader />
      <div id="main-content">
        <Routes>
          <Route path="/" element={<LandingView />} />
          <Route path="/related" element={<RelatedQuestionsView />} />
          <Route path="/solved" element={<SolvedView />} />
          <Route path="/tools" element={<RescueToolsView />} />
          <Route path="/tools/:tool" element={<ToolGuideView />} />
          <Route path="/chat/:conversationId" element={<ChatView />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AppFrame />
    </BrowserRouter>
  )
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20.5 14.4A8.5 8.5 0 0 1 9.6 3.5 8.5 8.5 0 1 0 20.5 14.4Z" />
    </svg>
  )
}

function HomeIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m3 11 9-8 9 8" />
      <path d="M5 10v10h14V10M9 20v-6h6v6" />
    </svg>
  )
}
