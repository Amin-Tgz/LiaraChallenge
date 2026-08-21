import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { recallQuestion } from '../flow'

const MCP_URL = 'https://liara-rescue-api.liara.run/mcp'

type HostGuide = {
  id: string
  name: string
  logo: string
  summary: string
  steps: string[]
  config?: string
  docsUrl: string
}

const MCP_HOSTS: HostGuide[] = [
  {
    id: 'claude',
    name: 'Claude Code',
    logo: '/brand/claude-code.ico',
    summary: 'نصب با CLI یا فایل پروژهٔ .mcp.json',
    steps: [
      'ترمینال را در پروژه باز کنید.',
      'دستور زیر را اجرا کنید. برای اشتراک تنظیم میان اعضای پروژه، --scope project را هم اضافه کنید.',
      'با claude mcp list اتصال و نمایش سه ابزار را بررسی کنید.',
    ],
    config: 'claude mcp add --transport http liara-docs ' + MCP_URL,
    docsUrl: 'https://code.claude.com/docs/en/mcp',
  },
  {
    id: 'cursor',
    name: 'Cursor',
    logo: '/brand/cursor.svg',
    summary: 'Settings → Tools & MCP یا فایل .cursor/mcp.json',
    steps: [
      'در Cursor وارد Settings و سپس Tools & MCP شوید.',
      'New MCP Server را بزنید؛ برای تنظیم پروژه‌ای فایل .cursor/mcp.json را بسازید.',
      'پس از ذخیره، سرور liara-docs باید سبز و ابزارهایش قابل مشاهده باشند.',
    ],
    config: '{\n  "mcpServers": {\n    "liara-docs": {\n      "url": "' + MCP_URL + '"\n    }\n  }\n}',
    docsUrl: 'https://docs.cursor.com/context/model-context-protocol',
  },
  {
    id: 'codex',
    name: 'Codex',
    logo: '/brand/codex.png',
    summary: 'Settings → MCP servers یا ~/.codex/config.toml',
    steps: [
      'در برنامهٔ Codex از Settings وارد MCP servers شوید و سرور جدید بسازید.',
      'همین اتصال را می‌توانید با CLI ثبت کنید؛ CLI، افزونهٔ IDE و برنامهٔ Codex تنظیم مشترک دارند.',
      'یک جلسهٔ تازه باز کنید و در فهرست tools به‌دنبال search، get_document و diagnose بگردید.',
    ],
    config: 'codex mcp add liara-docs --url ' + MCP_URL,
    docsUrl: 'https://developers.openai.com/codex/mcp/',
  },
  {
    id: 'openwebui',
    name: 'Open WebUI',
    logo: '/brand/open-webui.png',
    summary: 'Admin Settings → Integrations → Add Connection',
    steps: [
      'از نسخهٔ 0.6.31 یا جدیدتر و با حساب مدیر وارد Admin Settings شوید.',
      'در Integrations گزینهٔ Add Connection را بزنید و نوع MCP (Streamable HTTP) را انتخاب کنید.',
      'نام liara-docs و URL سرور را وارد کنید، ذخیره کنید و ابزارها را برای مدل موردنظر فعال کنید.',
    ],
    config: MCP_URL,
    docsUrl: 'https://docs.openwebui.com/features/extensibility/mcp/',
  },
  {
    id: 'jan',
    name: 'Jan',
    logo: '/brand/jan.svg',
    summary: 'Settings → MCP Servers → Add MCP Server',
    steps: [
      'در Jan وارد Settings و سپس MCP Servers شوید.',
      'Add MCP Server را انتخاب و transport را روی HTTP قرار دهید.',
      'URL زیر را ثبت کنید، سرور را روشن کنید و در یک گفت‌وگوی تازه ابزارها را آزمایش کنید.',
    ],
    config: MCP_URL,
    docsUrl: 'https://www.jan.ai/docs/desktop/integrations/mcp-servers',
  },
  {
    id: 'anythingllm',
    name: 'AnythingLLM',
    logo: '/brand/anythingllm.png',
    summary: 'مدیریت MCP در UI یا anythingllm_mcp_servers.json',
    steps: [
      'در تنظیمات Agent، بخش MCP Servers را باز کنید و سرور جدید اضافه کنید.',
      'نوع اتصال را Streamable HTTP و URL را مطابق نمونه قرار دهید.',
      'سرور را برای workspace فعال کنید و از Agent بخواهید ابزار search را صدا بزند.',
    ],
    config: '{\n  "liara-docs": {\n    "type": "streamable",\n    "url": "' + MCP_URL + '"\n  }\n}',
    docsUrl: 'https://docs.anythingllm.com/mcp-compatibility/overview',
  },
]

export default function ToolGuideView() {
  const { tool = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const passed = (location.state ?? {}) as { question?: string }
  const question = passed.question ?? recallQuestion()

  if (tool !== 'skill' && tool !== 'mcp') {
    return (
      <main className="shell shell-narrow">
        <section className="state-card">
          <h1>این ابزار وجود ندارد</h1>
          <button type="button" onClick={() => navigate('/tools', { state: { question } })}>
            بازگشت به ابزارهای نجات
          </button>
        </section>
      </main>
    )
  }

  return (
    <main className="shell guide-shell">
      {question && (
        <p className="original-question">
          <span className="label">سؤال شما:</span> {question}
        </p>
      )}
      {tool === 'skill' ? <SkillGuide /> : <McpGuide />}
      <button
        type="button"
        className="button-secondary"
        onClick={() => navigate('/tools', { state: { question } })}
      >
        بازگشت به ابزارهای نجات
      </button>
    </main>
  )
}

function SkillGuide() {
  return (
    <>
      <section className="guide-hero">
        <div>
          <span className="eyebrow">فایل نصب‌شدنی</span>
          <h1>افزودن Skill لیارا به دستیار کدنویسی</h1>
          <p className="lead">
            این فایل نقشهٔ مستندات رسمی، ساختار MDX و روش استخراج و استناد را به دستیار
            سازگار می‌دهد تا پاسخ‌های لیارا را کامل و دقیق و بدون حدس تولید کند. هیچ کلید
            محرمانه‌ای داخل Skill نیست.
          </p>
        </div>
        <a className="button-link download-button" href="/skill/SKILL.md" download>
          دانلود فایل SKILL.md
        </a>
      </section>

      <section className="guide-panel">
        <h2>نصب دستی</h2>
        <ol className="steps">
          <li>
            فایل را دانلود کنید و پوشه‌ای با نام <code className="inline-code">liara-docs-rescue</code>
            در مسیر Skillهای دستیار بسازید.
          </li>
          <li>
            برای Claude Code فایل را در
            <code className="inline-code">~/.claude/skills/liara-docs-rescue/SKILL.md</code>
            و برای Codex در
            <code className="inline-code">~/.codex/skills/liara-docs-rescue/SKILL.md</code>
            قرار دهید.
          </li>
          <li>دستیار را دوباره باز کنید و یک پرسش دربارهٔ لیارا بپرسید.</li>
        </ol>
        <div className="verification">
          <strong>نشانهٔ نصب درست</strong>
          <p>پاسخ باید منبع مستندات را ذکر کند و اگر شاهد کافی نیست، صریحاً از حدس‌زدن خودداری کند.</p>
        </div>
      </section>
    </>
  )
}

function McpGuide() {
  return (
    <>
      <section className="guide-hero">
        <div>
          <span className="eyebrow">Streamable HTTP · بدون کلید Liara</span>
          <h1>اتصال سرور MCP</h1>
          <p className="lead">
            این اتصال سه ابزار جست‌وجوی مستندات، خواندن صفحه و عیب‌یابی خطا را به میزبان
            شما می‌دهد. برنامه‌تان را انتخاب کنید تا جای فایل تنظیمات و مراحل دقیق را ببینید.
          </p>
        </div>
        <code className="endpoint-chip" dir="ltr">{MCP_URL}</code>
      </section>

      <section className="host-section" aria-labelledby="host-heading">
        <h2 id="host-heading">برنامهٔ میزبان را انتخاب کنید</h2>
        <div className="host-grid">
          {MCP_HOSTS.map((host) => (
            <details className="host-card" key={host.id}>
              <summary>
                <BrandMark logo={host.logo} name={host.name} id={host.id} />
                <span><strong>{host.name}</strong><small>{host.summary}</small></span>
                <span className="expand-mark" aria-hidden="true">+</span>
              </summary>
              <div className="host-detail">
                <ol className="steps">
                  {host.steps.map((step) => <li key={step}>{step}</li>)}
                </ol>
                {host.config && (
                  <div className="code-block compact-code">
                    <pre dir="ltr"><code>{host.config}</code></pre>
                  </div>
                )}
                <a href={host.docsUrl} target="_blank" rel="noreferrer noopener">
                  راهنمای رسمی {host.name}
                </a>
              </div>
            </details>
          ))}
        </div>
      </section>
    </>
  )
}

function BrandMark({ logo, name, id }: { logo: string; name: string; id: string }) {
  return (
    <span className={'host-logo host-logo-' + id} aria-hidden="true">
      <img src={logo} alt="" data-host-logo={name} loading="lazy" decoding="async" />
    </span>
  )
}
