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
    title: 'افزودن به دستیار کدنویسی‌تان',
    description:
      'اگر با Claude Code یا ابزار مشابهی کار می‌کنید، این مهارت را نصب می‌کنید تا دستیارتان پیش از پاسخ‌دادن، مستندات لیارا را جست‌وجو کند.',
    action: 'راهنمای نصب',
  },
  {
    name: 'mcp',
    title: 'اتصال مستقیم ابزارها',
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
