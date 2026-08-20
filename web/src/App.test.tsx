import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'

afterEach(() => vi.unstubAllGlobals())

test('renders each readiness check by name', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      json: async () => ({
        ready: false,
        checks: {
          postgres: { ok: true, latency_ms: 3 },
          active_index: { ok: false, reason: 'no_active_index_version' },
        },
      }),
    }),
  )

  render(<App />)

  await waitFor(() => expect(screen.getByText('postgres')).toBeDefined())
  expect(screen.getByText('active_index')).toBeDefined()
  // A failing check must state its own cause, never a generic message.
  expect(screen.getByText(/no_active_index_version/)).toBeDefined()
})
