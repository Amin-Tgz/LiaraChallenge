import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import LandingView from './views/LandingView'
import ToolGuideView from './views/ToolGuideView'
import DocsDemoView from './views/DocsDemoView'
import AdminView from './views/AdminView'
import App from './App'
import { AnswerFeedback } from './components/AnswerFeedback'
import { JobProgress } from './components/JobProgress'
import { Markdown } from './components/Markdown'
import { Citations } from './components/Citations'
import { ThinkingTrace } from './components/ThinkingTrace'
import type { FaqSearchResponse, TraceEvent } from './api/types'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  sessionStorage.clear()
  localStorage.clear()
})

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/session')) {
        return jsonResponse({ session_id: '11111111-1111-1111-1111-111111111111' })
      }
      if (url.endsWith('/chat/conversations') || url.endsWith('/faq/interactions')) {
        return jsonResponse([])
      }
      return jsonResponse({})
    }),
  )
})

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    json: async () => body,
  } as Response
}

const noop = () => undefined

const FAQ_RESULTS: FaqSearchResponse = {
  rescue_tools_available: false,
  results: [
    {
      faq_item_id: '22222222-2222-2222-2222-222222222222',
      question: 'چطور یک برنامه را روی لیارا مستقر کنم؟',
      answer: 'از دستور `liara deploy` استفاده کنید.',
      similarity: 0.71,
      source_url: 'https://docs.liara.ir/paas/about',
      source_commit: 'abc',
      tags: ['paas'],
    },
  ],
}

const EMPTY_FAQ: FaqSearchResponse = { rescue_tools_available: true, results: [] }

const STARTED_CONVERSATION = {
  conversation_id: '33333333-3333-3333-3333-333333333333',
  job: { id: 'job-1', status: 'queued' },
  created: true,
}

function landing() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<LandingView onConversationsChanged={noop} />} />
        <Route path="/chat/:conversationId" element={<p>صفحهٔ گفت‌وگو</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

// --- The chat-first entry point -------------------------------------------

test('the first screen is a composer, and it takes a paragraph rather than keywords', () => {
  landing()

  const field = screen.getByLabelText('سؤال شما')
  // A textarea, because these questions are paragraphs — an error message and
  // what was already tried — not search terms.
  expect(field.tagName).toBe('TEXTAREA')
  expect(screen.getByRole('button', { name: 'ارسال سؤال' })).toBeDefined()
})

test('a matching question is offered for the user to judge before any model call', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/faq/search')) return jsonResponse(FAQ_RESULTS)
    if (url.endsWith('/session')) {
      return jsonResponse({ session_id: '11111111-1111-1111-1111-111111111111' })
    }
    return jsonResponse([])
  })
  vi.stubGlobal('fetch', fetchMock)
  landing()

  await user.type(screen.getByLabelText('سؤال شما'), 'چطور مستقر کنم؟')
  await user.click(screen.getByRole('button', { name: 'ارسال سؤال' }))

  await waitFor(() =>
    expect(screen.getByText('چطور یک برنامه را روی لیارا مستقر کنم؟')).toBeDefined(),
  )
  // Nothing is generated until the user says the documentation did not help.
  expect(
    fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/chat/conversations')),
  ).toHaveLength(0)
  expect(screen.getByRole('button', { name: 'نه، از دستیار بپرس' })).toBeDefined()
})

test('rejecting the offered questions opens a conversation with the same wording', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/faq/search')) return jsonResponse(FAQ_RESULTS)
    if (url.endsWith('/session')) {
      return jsonResponse({ session_id: '11111111-1111-1111-1111-111111111111' })
    }
    if (url.endsWith('/chat/conversations') && init?.method === 'POST') {
      return jsonResponse(STARTED_CONVERSATION)
    }
    return jsonResponse([])
  })
  vi.stubGlobal('fetch', fetchMock)
  landing()

  await user.type(screen.getByLabelText('سؤال شما'), 'چطور مستقر کنم؟')
  await user.click(screen.getByRole('button', { name: 'ارسال سؤال' }))
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'نه، از دستیار بپرس' })).toBeDefined(),
  )
  await user.click(screen.getByRole('button', { name: 'نه، از دستیار بپرس' }))

  await waitFor(() => expect(screen.getByText('صفحهٔ گفت‌وگو')).toBeDefined())
  const started = fetchMock.mock.calls.find(
    ([input, init]) =>
      String(input).endsWith('/chat/conversations') &&
      (init as RequestInit | undefined)?.method === 'POST',
  )
  // Sent verbatim: the user never retypes and we never paraphrase for them.
  expect(String((started?.[1] as RequestInit).body)).toContain('چطور مستقر کنم؟')
})

test('a search that matches nothing goes straight to the assistant', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/faq/search')) return jsonResponse(EMPTY_FAQ)
      if (url.endsWith('/session')) {
        return jsonResponse({ session_id: '11111111-1111-1111-1111-111111111111' })
      }
      if (url.endsWith('/chat/conversations') && init?.method === 'POST') {
        return jsonResponse(STARTED_CONVERSATION)
      }
      return jsonResponse([])
    }),
  )
  landing()

  await user.type(screen.getByLabelText('سؤال شما'), 'پرسشی که هیچ تطبیقی ندارد')
  await user.click(screen.getByRole('button', { name: 'ارسال سؤال' }))

  // No gate to click through when there is nothing to offer.
  await waitFor(() => expect(screen.getByText('صفحهٔ گفت‌وگو')).toBeDefined())
})

test('a failing search reports its cause and does not advance', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/faq/search')) {
        return jsonResponse(
          {
            error: {
              code: 'NO_ACTIVE_INDEX',
              message: 'هنوز هیچ مستندی ایندکس نشده است.',
            },
          },
          503,
        )
      }
      return jsonResponse([])
    }),
  )
  landing()

  await user.type(screen.getByLabelText('سؤال شما'), 'چطور مستقر کنم؟')
  await user.click(screen.getByRole('button', { name: 'ارسال سؤال' }))

  // NO_ACTIVE_INDEX is a system failure and must never read as "no results".
  await waitFor(() =>
    expect(screen.getByRole('alert').textContent).toContain('هنوز هیچ مستندی ایندکس نشده'),
  )
  expect(screen.queryByRole('button', { name: 'نه، از دستیار بپرس' })).toBeNull()
})

test('Enter submits the question while Shift+Enter keeps a newline', async () => {
  const user = userEvent.setup()
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/faq/search')) return jsonResponse(FAQ_RESULTS)
    if (url.endsWith('/session')) {
      return jsonResponse({ session_id: '11111111-1111-1111-1111-111111111111' })
    }
    return jsonResponse([])
  })
  vi.stubGlobal('fetch', fetchMock)
  landing()

  const field = screen.getByLabelText('سؤال شما')
  await user.type(field, 'خط اول')
  await user.keyboard('{Shift>}{Enter}{/Shift}')
  expect((field as HTMLTextAreaElement).value).toContain('\n')
  expect(
    fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/faq/search')),
  ).toHaveLength(0)

  await user.keyboard('{Enter}')
  await waitFor(() =>
    expect(screen.getByText('چطور یک برنامه را روی لیارا مستقر کنم؟')).toBeDefined(),
  )
})

// --- Showing the work ------------------------------------------------------

const TRACE: TraceEvent[] = [
  {
    step: 1,
    tool: 'search_docs',
    query: 'استقرار جنگو',
    result_count: 4,
    top_similarity: 0.62,
    status: 'ok',
    elapsed_ms: 900,
  },
  {
    step: 2,
    tool: 'read_doc',
    query: 'https://docs.liara.ir/paas/django',
    result_count: 1,
    top_similarity: null,
    status: 'ok',
    elapsed_ms: 1500,
  },
]

test('the trace names the real steps, in Persian, with what each one found', () => {
  render(<ThinkingTrace steps={TRACE} running />)

  expect(screen.getByText('جست‌وجو در مستندات')).toBeDefined()
  expect(screen.getByText('«استقرار جنگو»')).toBeDefined()
  expect(screen.getByText(/4 نتیجه/)).toBeDefined()
  expect(screen.getByText(/62٪/)).toBeDefined()
})

test('a step with no measured similarity does not print a fabricated number', () => {
  render(<ThinkingTrace steps={[TRACE[1]]} running />)

  // "Not measured" and "measured as zero" are different facts.
  expect(screen.getByText('1 نتیجه').textContent).not.toContain('٪')
})

test('an empty trace renders nothing rather than an empty panel', () => {
  const { container } = render(<ThinkingTrace steps={[]} running />)
  expect(container.querySelector('.thinking-trace')).toBeNull()
})

test('a failed job states its cause rather than a generic message', () => {
  render(
    <JobProgress
      status="failed"
      errorCode="ALL_PROVIDERS_UNAVAILABLE"
      errorMessage="سرویس پاسخ‌گویی موقتاً در دسترس نیست. سؤال شما ذخیره شد."
    />,
  )

  const alert = screen.getByRole('alert')
  expect(alert.textContent).toContain('سرویس پاسخ‌گویی موقتاً در دسترس نیست')
  expect(alert.textContent).toContain('ALL_PROVIDERS_UNAVAILABLE')
})

test('every job state is described in plain language', () => {
  for (const status of ['queued', 'retrieving', 'generating', 'retrying'] as const) {
    const { unmount } = render(<JobProgress status={status} attempt={1} maxAttempts={3} />)
    const region = screen.getByRole('status')
    expect(region.textContent?.trim().length ?? 0).toBeGreaterThan(10)
    expect(region.getAttribute('aria-live')).toBe('polite')
    expect(screen.getByTestId('thinking-frame').getAttribute('src')).toBe('/images/think1.png')
    unmount()
  }
})

// --- Judging an answer -----------------------------------------------------

test('rejecting an answer asks which kind of wrong it was', async () => {
  const user = userEvent.setup()
  render(<AnswerFeedback messageId="m1" existing={null} />)

  await user.click(screen.getByRole('button', { name: 'نه، این پاسخ کمک نکرد' }))

  // "Bad" is not actionable; "incomplete" points at the corpus and
  // "irrelevant" at retrieval.
  for (const label of ['نادرست بود', 'ناقص بود', 'به سؤالم ربط نداشت', 'منبعش اشتباه بود']) {
    expect(screen.getByRole('button', { name: label })).toBeDefined()
  }
})

test('a failing feedback call never disturbs the answer the user is reading', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse({ error: { code: 'INTERNAL_ERROR', message: 'خطا' } }, 500)),
  )
  vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  render(<AnswerFeedback messageId="m1" existing={null} />)

  await user.click(screen.getByRole('button', { name: 'بله، این پاسخ کمک کرد' }))

  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('ثبت شد'))
  expect(screen.queryByRole('alert')).toBeNull()
})

test('a verdict already recorded is shown back instead of asked again', () => {
  render(<AnswerFeedback messageId="m1" existing={{ outcome: 'resolved', reason: null }} />)

  expect(screen.getByRole('status').textContent).toContain('ثبت شد')
  expect(screen.queryByRole('button', { name: 'بله، این پاسخ کمک کرد' })).toBeNull()
})

// --- Rendering answers -----------------------------------------------------

test('code blocks render left-to-right with a copy control', () => {
  render(<Markdown>{'برای استقرار:\n\n```bash\nliara deploy --port 8000\n```'}</Markdown>)

  const pre = document.querySelector('pre')
  // A shell command reordered by the bidi algorithm is a command that does not run.
  expect(pre?.getAttribute('dir')).toBe('ltr')
  expect(screen.getByRole('button', { name: 'کپی کد' })).toBeDefined()
})

test('mixed Persian and Latin inline text keeps the code element isolated', () => {
  render(<Markdown>{'دستور `liara deploy` را اجرا کنید.'}</Markdown>)

  const code = document.querySelector('code.inline-code')
  expect(code?.textContent).toBe('liara deploy')
  expect(code?.getAttribute('dir')).toBe('ltr')
})

test('citations show the page title and section, and deep-link to the anchor', () => {
  render(
    <Citations
      citations={[
        {
          evidence_id: 'e1',
          url: 'https://docs.liara.ir/paas/django/how-tos/create-app#steps',
          page_title: 'ساخت برنامه‌ی Django',
          section_title: 'مراحل',
          source_commit: 'abc',
        },
      ]}
    />,
  )

  const link = within(screen.getByRole('list')).getByRole('link')
  expect(link.getAttribute('href')).toContain('#steps')
  expect(link.textContent).toContain('ساخت برنامه‌ی Django')
  expect(link.textContent).toContain('مراحل')
})

test('a cited image is beside its citation and falls back to alt text without losing the answer', () => {
  render(
    <div>
      <p>پاسخ همچنان قابل خواندن است.</p>
      <Citations
        citations={[
          {
            evidence_id: 'e1',
            url: 'https://docs.liara.ir/paas/django#deploy',
            page_title: 'استقرار Django',
            section_title: 'مراحل',
            source_commit: 'abc',
          },
        ]}
        images={[
          {
            evidence_id: 'e1',
            url: 'https://media.liara.ir/missing.png',
            alt: 'نمای دکمهٔ استقرار در پنل',
          },
        ]}
      />
    </div>,
  )

  const citation = screen.getByRole('listitem')
  const image = within(citation).getByRole('img', { name: 'نمای دکمهٔ استقرار در پنل' })
  expect(image.tagName).toBe('IMG')

  fireEvent.error(image)

  const fallback = within(citation).getByRole('img', {
    name: 'نمای دکمهٔ استقرار در پنل',
  })
  expect(fallback.tagName).toBe('P')
  expect(fallback.textContent).toContain('نمای دکمهٔ استقرار در پنل')
  expect(screen.getByText('پاسخ همچنان قابل خواندن است.')).toBeDefined()
  expect(document.querySelector('img')).toBeNull()
})

// --- Rescue tools ----------------------------------------------------------

test('the Skill guide exposes a real downloadable file and its illustration', () => {
  render(
    <MemoryRouter initialEntries={['/tools/skill']}>
      <Routes>
        <Route path="/tools/:tool" element={<ToolGuideView />} />
      </Routes>
    </MemoryRouter>,
  )

  const download = screen.getByRole('link', { name: 'دانلود فایل SKILL.md' })
  expect(download.getAttribute('href')).toBe('/skill/SKILL.md')
  expect(download.hasAttribute('download')).toBe(true)
  expect(screen.getByRole('img', { name: /Skill لیارا/ }).getAttribute('src')).toBe(
    '/images/skill.png',
  )
})

test('the MCP guide provides a selectable card for each supported host', async () => {
  const user = userEvent.setup()
  render(
    <MemoryRouter initialEntries={['/tools/mcp']}>
      <Routes>
        <Route path="/tools/:tool" element={<ToolGuideView />} />
      </Routes>
    </MemoryRouter>,
  )

  for (const host of ['Claude Code', 'Cursor', 'Codex', 'Open WebUI', 'Jan', 'AnythingLLM']) {
    expect(screen.getByText(host)).toBeDefined()
    expect(document.querySelector('[data-host-logo="' + host + '"]')).not.toBeNull()
  }
  expect(screen.getByRole('img', { name: /MCP/ }).getAttribute('src')).toBe('/images/MCP.png')
  await user.click(screen.getByText('Claude Code'))
  expect(screen.getByText(/claude mcp add --transport http/)).toBeDefined()
})

// --- The documentation demo ------------------------------------------------

test('the demo page says plainly that it is not the real documentation', () => {
  render(
    <MemoryRouter initialEntries={['/demo']}>
      <Routes>
        <Route path="/demo" element={<DocsDemoView />} />
      </Routes>
    </MemoryRouter>,
  )

  const note = screen.getByRole('note')
  expect(note.textContent).toContain('صفحهٔ نمایشی')
  expect(within(note).getByRole('link').getAttribute('href')).toBe('https://docs.liara.ir/')
})

test('the widget is reachable by keyboard and leads into the assistant', async () => {
  const user = userEvent.setup()
  render(
    <MemoryRouter initialEntries={['/demo']}>
      <Routes>
        <Route path="/demo" element={<DocsDemoView />} />
        <Route path="/" element={<p>صفحهٔ اصلی</p>} />
      </Routes>
    </MemoryRouter>,
  )

  const widget = screen.getByRole('button', { name: /دستیار لیارا را باز کن/ })
  widget.focus()
  expect(document.activeElement).toBe(widget)
  await user.keyboard('{Enter}')
  await waitFor(() => expect(screen.getByText('صفحهٔ اصلی')).toBeDefined())
})

// --- Admin -----------------------------------------------------------------

test('the admin console asks for credentials before showing anything', () => {
  render(
    <MemoryRouter initialEntries={['/admin']}>
      <Routes>
        <Route path="/admin" element={<AdminView />} />
      </Routes>
    </MemoryRouter>,
  )

  expect(screen.getByLabelText('نام کاربری')).toBeDefined()
  expect(screen.getByLabelText('رمز عبور')).toBeDefined()
  expect(screen.queryByRole('tab', { name: 'بازخوردها' })).toBeNull()
})

test('a rejected admin login reports the cause and writes nothing to browser storage', async () => {
  const user = userEvent.setup()
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, 401)))
  render(
    <MemoryRouter initialEntries={['/admin']}>
      <Routes>
        <Route path="/admin" element={<AdminView />} />
      </Routes>
    </MemoryRouter>,
  )

  await user.type(screen.getByLabelText('نام کاربری'), 'admin')
  await user.type(screen.getByLabelText('رمز عبور'), 'wrong')
  await user.click(screen.getByRole('button', { name: 'ورود' }))

  await waitFor(() => expect(screen.getByRole('alert')).toBeDefined())
  expect(screen.queryByRole('tab', { name: 'بازخوردها' })).toBeNull()
  // An administrator's password never reaches disk in the browser.
  expect(localStorage.length).toBe(0)
  expect(sessionStorage.length).toBe(0)
})

test('a cited page in the statistics is a link to the page, not inert text', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/admin/dashboard')) {
        return jsonResponse({
          window_days: 30,
          metrics: {
            top_cited_pages: {
              value: [
                { source_url: 'https://docs.liara.ir/paas/django/deploy', count: 12 },
              ],
              sample_size: 12,
              unit: 'events',
              no_data: false,
            },
          },
        })
      }
      return jsonResponse({ items: [], total: 0 })
    }),
  )
  render(
    <MemoryRouter initialEntries={['/admin']}>
      <Routes>
        <Route path="/admin" element={<AdminView />} />
      </Routes>
    </MemoryRouter>,
  )

  await user.type(screen.getByLabelText('نام کاربری'), 'admin')
  await user.type(screen.getByLabelText('رمز عبور'), 'secret')
  await user.click(screen.getByRole('button', { name: 'ورود' }))
  await user.click(await screen.findByRole('tab', { name: 'آمار' }))

  const link = await screen.findByRole('link', { name: '/paas/django/deploy' })
  expect(link.getAttribute('href')).toBe('https://docs.liara.ir/paas/django/deploy')
  // The full address stays reachable even though the visible text is the path.
  expect(link.getAttribute('title')).toBe('https://docs.liara.ir/paas/django/deploy')
})

// --- Shell -----------------------------------------------------------------

test('the explicit theme control persists the selected light or dark theme', async () => {
  const user = userEvent.setup()
  render(<App />)

  const toggle = screen.getByRole('button', { name: 'فعال‌کردن حالت تیره' })
  await user.click(toggle)
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(localStorage.getItem('rescue.theme')).toBe('dark')
})

test('the sidebar drawer opens from the header and closes with Escape', async () => {
  const user = userEvent.setup()
  render(<App />)

  await user.click(screen.getByRole('button', { name: 'باز کردن فهرست گفت‌وگوها' }))
  expect(
    screen.getByRole('button', { name: 'بستن فهرست گفت‌وگوها' }).getAttribute('aria-expanded'),
  ).toBe('true')

  await user.keyboard('{Escape}')
  await waitFor(() =>
    expect(
      screen
        .getByRole('button', { name: 'باز کردن فهرست گفت‌وگوها' })
        .getAttribute('aria-expanded'),
    ).toBe('false'),
  )
  // Focus returns to the control that opened it, so keyboard use continues.
  expect(document.activeElement).toBe(
    screen.getByRole('button', { name: 'باز کردن فهرست گفت‌وگوها' }),
  )
})

test('Skill and MCP live in the sidebar, beside the conversation history', () => {
  render(<App />)

  const sidebar = screen.getByRole('navigation', { name: 'گفت‌وگوها و ابزارها' })
  expect(within(sidebar).getByRole('link', { name: /Skill لیارا/ })).toBeDefined()
  expect(within(sidebar).getByRole('link', { name: /سرور MCP/ })).toBeDefined()
  expect(within(sidebar).getByRole('button', { name: /گفت‌وگوی جدید/ })).toBeDefined()
})

test('a prior conversation can be deleted from the sidebar', async () => {
  const user = userEvent.setup()
  const conversationId = '44444444-4444-4444-8444-444444444444'
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/chat/conversations') && !init?.method) {
      return jsonResponse([
        {
          id: conversationId,
          initial_question: 'چطور برنامه را مستقر کنم؟',
          title: null,
          rescue_tool: 'chat',
          message_count: 4,
        },
      ])
    }
    if (url.endsWith(`/chat/conversations/${conversationId}`) && init?.method === 'DELETE') {
      return jsonResponse(null, 204)
    }
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  render(<App />)

  const remove = await screen.findByRole('button', { name: /حذف گفت‌وگوی چطور برنامه/ })
  await user.click(remove)

  await waitFor(() => expect(screen.queryByRole('button', { name: /حذف گفت‌وگو/ })).toBeNull())
  expect(
    fetchMock.mock.calls.some(
      ([input, init]) =>
        String(input).endsWith(`/chat/conversations/${conversationId}`) &&
        init?.method === 'DELETE',
    ),
  ).toBe(true)
})
