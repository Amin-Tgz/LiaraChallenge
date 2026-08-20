/**
 * The rescue flow.
 *
 * Every stage owns a URL, which is what makes the flow survive a reload and a
 * shared link. The chat stage carries the conversation id, so reopening it
 * rebuilds the transcript from the server rather than from anything held in
 * memory.
 */

import { BrowserRouter, Link, Route, Routes, useNavigate } from 'react-router-dom'
import ChatView from './views/ChatView'
import LandingView from './views/LandingView'
import RelatedQuestionsView from './views/RelatedQuestionsView'
import RescueToolsView from './views/RescueToolsView'
import ToolGuideView from './views/ToolGuideView'
import { recallQuestion } from './flow'

function SolvedView() {
  const navigate = useNavigate()
  return (
    <main className="shell">
      <h1>خوشحالیم که حل شد</h1>
      <p className="lead">
        بازخورد شما ثبت شد و به بهتر شدن پاسخ‌های بعدی کمک می‌کند.
      </p>
      <button type="button" onClick={() => navigate('/')}>
        پرسش تازه
      </button>
    </main>
  )
}

function NotFound() {
  return (
    <main className="shell">
      <h1>این صفحه وجود ندارد</h1>
      <p>
        نشانی واردشده به هیچ بخشی از دستیار نجات اشاره نمی‌کند.{' '}
        <Link to="/">بازگشت به صفحه‌ی اول</Link>
      </p>
    </main>
  )
}

export default function App() {
  return (
    <BrowserRouter
      // Opt in to the v6.4+ behaviour React Router warns about, so the console
      // stays clean and the upgrade to v7 is not a behaviour change.
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <a className="skip-link" href="#main-content">
        پرش به محتوای اصلی
      </a>
      <header className="masthead">
        <Link to="/" onClick={() => recallQuestion()}>
          دستیار نجات مستندات لیارا
        </Link>
      </header>

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
    </BrowserRouter>
  )
}
