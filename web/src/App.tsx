import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BrowserRouter,
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom'
import { listConversations } from './api/client'
import type { ConversationSummary } from './api/types'
import { Sidebar } from './components/Sidebar'
import AdminView from './views/AdminView'
import ChatView from './views/ChatView'
import DocsDemoView from './views/DocsDemoView'
import LandingView from './views/LandingView'
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

function AppHeader({
  onToggleSidebar,
  sidebarOpen,
  menuRef,
}: {
  onToggleSidebar: () => void
  sidebarOpen: boolean
  menuRef: React.RefObject<HTMLButtonElement>
}) {
  return (
    <header className="masthead">
      <div className="masthead-inner">
        <button
          type="button"
          className="icon-button menu-button"
          onClick={onToggleSidebar}
          aria-expanded={sidebarOpen}
          aria-label={sidebarOpen ? 'بستن فهرست گفت‌وگوها' : 'باز کردن فهرست گفت‌وگوها'}
          ref={menuRef}
        >
          <MenuIcon />
        </button>

        <Link className="brand" to="/" aria-label="دستیار نجات مستندات لیارا؛ صفحهٔ اصلی">
          <img className="brand-mark" src="/images/logoLiara.png" alt="" aria-hidden="true" />
          <span>
            <strong>نجات مستندات لیارا</strong>
            <small>پاسخ مستند، بدون حدس</small>
          </span>
        </Link>

        <nav className="header-actions" aria-label="ابزارهای صفحه">
          <NavLink
            className={({ isActive }) => 'header-tab' + (isActive ? ' active' : '')}
            to="/demo"
          >
            صفحهٔ تست
          </NavLink>
          <NavLink
            className={({ isActive }) => 'header-tab' + (isActive ? ' active' : '')}
            to="/admin"
          >
            ادمین
          </NavLink>
          <ThemeToggle />
        </nav>
      </div>
    </header>
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
  const location = useLocation()
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [drawerOpen, setDrawerOpen] = useState(false)
  // Held here rather than in the header so closing the drawer from inside it
  // can hand focus back to the control that opened it.
  const menuRef = useRef<HTMLButtonElement>(null)

  const refreshConversations = useCallback(() => {
    listConversations()
      .then(setConversations)
      .catch(() => {
        // History is a convenience. An unreachable list must not blank the app.
      })
  }, [])

  useEffect(() => {
    refreshConversations()
  }, [refreshConversations])

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false)
    menuRef.current?.focus()
  }, [menuRef])

  // The demo page stands in for somebody else's site, so it gets none of our
  // chrome — a masthead over it would give away the illusion it exists to make.
  const bare = location.pathname === '/demo'
  if (bare) {
    return (
      <Routes>
        <Route path="/demo" element={<DocsDemoView />} />
      </Routes>
    )
  }

  return (
    <>
      <a className="skip-link" href="#main-content">پرش به محتوای اصلی</a>
      <AppHeader
        onToggleSidebar={() => setDrawerOpen((open) => !open)}
        sidebarOpen={drawerOpen}
        menuRef={menuRef}
      />
      <div className="app-body">
        <Sidebar conversations={conversations} open={drawerOpen} onClose={closeDrawer} />
        <div id="main-content" className="app-content">
          <Routes>
            <Route
              path="/"
              element={<LandingView onConversationsChanged={refreshConversations} />}
            />
            <Route
              path="/chat/:conversationId"
              element={<ChatView onConversationsChanged={refreshConversations} />}
            />
            <Route path="/tools/:tool" element={<ToolGuideView />} />
            <Route path="/admin" element={<AdminView />} />
            {/* The old multi-page rescue path folded into the chat surface. */}
            <Route path="/related" element={<Navigate to="/" replace />} />
            <Route path="/tools" element={<Navigate to="/" replace />} />
            <Route path="/solved" element={<Navigate to="/" replace />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
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

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  )
}
