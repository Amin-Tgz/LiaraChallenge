/**
 * The three ways out, described by what they do rather than what they are.
 *
 * "MCP server" means nothing to someone who is stuck. Each option is therefore
 * introduced by the situation it suits. The original question travels with the
 * user into whichever one they pick — they never retype it.
 */

import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  ApiError,
  fireAndForget,
  getSessionId,
  newIdempotencyKey,
  recordInteraction,
  startConversation,
} from '../api/client'
import type { RescueToolName } from '../api/types'
import { recallQuestion } from '../flow'

type Tool = {
  name: RescueToolName
  title: string
  description: string
  action: string
}

const TOOLS: Tool[] = [
  {
    name: 'chat',
    title: 'گفت‌وگو با دستیار',
    description:
      'همین‌جا سؤالتان را می‌پرسید و پاسخی می‌گیرید که هر ادعای فنی‌اش به مستندات لیارا ارجاع دارد. اگر شواهد کافی نباشد، حدس نمی‌زند و همین را می‌گوید.',
    action: 'شروع گفت‌وگو',
  },
  {
    name: 'skill',
    title: 'افزودن Skill لیارا به دستیار کدنویسی',
    description:
      'فایل Skill را دانلود و در دستیار سازگار نصب کنید تا هنگام پرسش دربارهٔ لیارا، روش جست‌وجوی مستند و قواعد استناد را در اختیار داشته باشد.',
    action: 'دانلود و راهنمای نصب',
  },
  {
    name: 'mcp',
    title: 'اتصال سرور MCP',
    description:
      'یک سرور MCP که جست‌وجو در مستندات، خواندن یک صفحه و عیب‌یابی را به‌صورت ابزار در اختیار هر میزبان سازگار می‌گذارد.',
    action: 'راهنمای اتصال',
  },
]

export default function RescueToolsView() {
  const navigate = useNavigate()
  const location = useLocation()
  const passed = (location.state ?? {}) as { question?: string }
  const question = passed.question ?? recallQuestion()

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [busy, setBusy] = useState<RescueToolName | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getSessionId()
      .then(({ session_id }) => setSessionId(session_id))
      .catch(() => setSessionId(null))
  }, [])

  async function choose(tool: RescueToolName) {
    if (sessionId && question) {
      fireAndForget(
        recordInteraction({
          event_type: 'rescue_tool_transition',
          session_id: sessionId,
          question,
          rescue_tool: tool,
        }),
      )
    }

    if (tool !== 'chat') {
      navigate(`/tools/${tool}`, { state: { question } })
      return
    }

    setBusy('chat')
    setError(null)
    try {
      // The question the user already typed starts the conversation.
      const response = await startConversation(question, newIdempotencyKey())
      navigate(`/chat/${response.conversation_id}`, {
        state: { jobId: response.job.id, question },
      })
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : 'ارتباط با سرویس برقرار نشد.',
      )
    } finally {
      setBusy(null)
    }
  }

  return (
    <main className="shell">
      <span className="eyebrow">اگر پرسش مرتبط کافی نبود</span>
      <h1>ابزارهای نجات</h1>
      {question && (
        <p className="original-question">
          <span className="label">سؤال شما:</span> {question}
        </p>
      )}
      <p className="lead">
        سه راه برای رسیدن به پاسخ. سؤالتان در هر سه حفظ می‌شود.
      </p>

      <ul className="tools">
        {TOOLS.map((tool) => (
          <li key={tool.name}>
            <span className={'tool-icon tool-icon-' + tool.name} aria-hidden="true">
              {tool.name === 'chat' ? 'گ' : tool.name === 'skill' ? 'S' : 'M'}
            </span>
            <h2>{tool.title}</h2>
            <p>{tool.description}</p>
            <button
              type="button"
              onClick={() => void choose(tool.name)}
              disabled={busy !== null || (tool.name === 'chat' && !question)}
            >
              {busy === tool.name ? 'در حال آماده‌سازی…' : tool.action}
            </button>
          </li>
        ))}
      </ul>

      {error && (
        <p role="alert" className="job-error">
          {error}
        </p>
      )}
    </main>
  )
}
