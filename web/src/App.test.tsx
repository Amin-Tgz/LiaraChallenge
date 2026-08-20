import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import LandingView from './views/LandingView'
import RelatedQuestionsView from './views/RelatedQuestionsView'
import RescueToolsView from './views/RescueToolsView'
import { JobProgress } from './components/JobProgress'
import { Markdown } from './components/Markdown'
import { Citations } from './components/Citations'
import type { FaqSearchResponse } from './api/types'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  sessionStorage.clear()
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

test('the landing view takes a multi-line question, not a search box', () => {
  render(
    <MemoryRouter>
      <LandingView />
    </MemoryRouter>,
  )

  const field = screen.getByLabelText('سؤال شما')
  // A textarea, because these questions are paragraphs — an error message and
  // what was already tried — not keywords.
  expect(field.tagName).toBe('TEXTAREA')
  expect(Number(field.getAttribute('rows'))).toBeGreaterThan(1)
})

test('results are labelled as related questions, never as answers', () => {
  render(
    <MemoryRouter
      initialEntries={[
        { pathname: '/related', state: { question: 'سؤال من', results: FAQ_RESULTS } },
      ]}
    >
      <Routes>
        <Route path="/related" element={<RelatedQuestionsView />} />
      </Routes>
    </MemoryRouter>,
  )

  expect(screen.getByRole('heading', { name: 'پرسش‌های مرتبط' })).toBeDefined()
  expect(screen.getByText(/نه لزوماً پاسخ/)).toBeDefined()
})

test('a below-threshold result shows the gap state and offers rescue tools', () => {
  render(
    <MemoryRouter
      initialEntries={[
        {
          pathname: '/related',
          state: {
            question: 'سؤال من',
            results: { results: [], rescue_tools_available: true },
          },
        },
      ]}
    >
      <Routes>
        <Route path="/related" element={<RelatedQuestionsView />} />
      </Routes>
    </MemoryRouter>,
  )

  // "Nothing matched" must read as a documentation gap, not as a broken system.
  expect(screen.getByRole('heading', { name: 'پرسش مشابهی پیدا نشد' })).toBeDefined()
  expect(screen.getByText(/مستندات جست‌وجو شدند/)).toBeDefined()
  expect(screen.getByRole('button', { name: /ابزارهای نجات/ })).toBeDefined()
})

test('the rescue tools view keeps the original question', () => {
  sessionStorage.setItem('rescue.question', 'چرا استقرار من شکست می‌خورد؟')

  render(
    <MemoryRouter initialEntries={['/tools']}>
      <Routes>
        <Route path="/tools" element={<RescueToolsView />} />
      </Routes>
    </MemoryRouter>,
  )

  // Carried across the transition, so the user never retypes it.
  expect(screen.getByText('چرا استقرار من شکست می‌خورد؟')).toBeDefined()
  expect(screen.getByRole('heading', { name: 'گفت‌وگو با دستیار' })).toBeDefined()
  expect(screen.getByRole('heading', { name: /دستیار کدنویسی/ })).toBeDefined()
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
    unmount()
  }
})

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

test('submitting the landing question routes to related questions', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/faq/search')) return jsonResponse(FAQ_RESULTS)
      return jsonResponse([])
    }),
  )

  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<LandingView />} />
        <Route path="/related" element={<RelatedQuestionsView />} />
      </Routes>
    </MemoryRouter>,
  )

  await user.type(screen.getByLabelText('سؤال شما'), 'چطور مستقر کنم؟')
  await user.click(screen.getByRole('button', { name: 'پیدا کردن پاسخ' }))

  await waitFor(() =>
    expect(screen.getByRole('heading', { name: 'پرسش‌های مرتبط' })).toBeDefined(),
  )
  // The question survives the transition.
  expect(sessionStorage.getItem('rescue.question')).toBe('چطور مستقر کنم؟')
})

test('a failing search reports the cause and does not advance the flow', async () => {
  const user = userEvent.setup()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/faq/search')) {
        return jsonResponse(
          { error: { code: 'NO_ACTIVE_INDEX', message: 'هنوز هیچ مستندی ایندکس نشده است.' } },
          503,
        )
      }
      return jsonResponse([])
    }),
  )

  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<LandingView />} />
        <Route path="/related" element={<RelatedQuestionsView />} />
      </Routes>
    </MemoryRouter>,
  )

  await user.type(screen.getByLabelText('سؤال شما'), 'چطور مستقر کنم؟')
  await user.click(screen.getByRole('button', { name: 'پیدا کردن پاسخ' }))

  // NO_ACTIVE_INDEX is a system failure and must never be shown as "no results".
  await waitFor(() =>
    expect(screen.getByRole('alert').textContent).toContain('هنوز هیچ مستندی ایندکس نشده'),
  )
  expect(screen.queryByRole('heading', { name: 'پرسش‌های مرتبط' })).toBeNull()
})
