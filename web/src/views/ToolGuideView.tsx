/**
 * Installation guidance for the two non-chat rescue tools.
 *
 * The user's question stays on screen throughout: someone who came here to
 * install a Skill still has a problem to solve, and switching back to chat must
 * not cost them the thing they typed.
 */

import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { Markdown } from '../components/Markdown'
import { recallQuestion } from '../flow'

const GUIDES: Record<string, { title: string; body: string }> = {
  skill: {
    title: 'نصب مهارت در دستیار کدنویسی',
    body: `این مهارت به دستیار کدنویسی شما یاد می‌دهد که پیش از پاسخ‌دادن درباره‌ی لیارا، مستندات رسمی را جست‌وجو کند و بدون شواهد پاسخ نسازد.

۱. پوشه‌ی مهارت را در مسیر مهارت‌های دستیارتان قرار دهید:

\`\`\`bash
mkdir -p ~/.claude/skills/liara-docs
curl -o ~/.claude/skills/liara-docs/SKILL.md \\
  https://liara-rescue-api.liara.run/skill/SKILL.md
\`\`\`

۲. دستیار را دوباره اجرا کنید و سؤالتان را بپرسید. مهارت به‌طور خودکار فعال می‌شود.

۳. برای آزمودن، این سؤال را بپرسید:

\`\`\`text
چطور یک برنامه‌ی Django را روی لیارا مستقر کنم؟
\`\`\`

پاسخ باید به صفحه‌ای از مستندات لیارا ارجاع بدهد.`,
  },
  mcp: {
    title: 'اتصال سرور MCP',
    body: `سرور MCP سه ابزار در اختیار میزبان شما می‌گذارد: جست‌وجوی مستندات، خواندن یک صفحه، و عیب‌یابی یک خطا.

این پیکربندی را به فایل تنظیمات میزبان MCP خود اضافه کنید:

\`\`\`json
{
  "mcpServers": {
    "liara-docs": {
      "url": "https://liara-rescue-api.liara.run/mcp"
    }
  }
}
\`\`\`

سپس میزبان را دوباره راه‌اندازی کنید. ابزارها باید در فهرست ابزارهای در دسترس دیده شوند.`,
  },
}

export default function ToolGuideView() {
  const { tool = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const passed = (location.state ?? {}) as { question?: string }
  const question = passed.question ?? recallQuestion()
  const guide = GUIDES[tool]

  if (!guide) {
    return (
      <main className="shell">
        <p role="alert">ابزاری با این نام وجود ندارد.</p>
        <button type="button" onClick={() => navigate('/tools', { state: { question } })}>
          بازگشت به ابزارهای نجات
        </button>
      </main>
    )
  }

  return (
    <main className="shell">
      <h1>{guide.title}</h1>
      {question && (
        <p className="original-question">
          <span className="label">سؤال شما:</span> {question}
        </p>
      )}
      <Markdown>{guide.body}</Markdown>
      <button type="button" onClick={() => navigate('/tools', { state: { question } })}>
        بازگشت به ابزارهای نجات
      </button>
    </main>
  )
}
