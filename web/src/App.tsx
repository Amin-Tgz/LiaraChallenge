import { useEffect, useState } from 'react'

type Check = { ok: boolean; latency_ms?: number; reason?: string }
type Readiness = { ready: boolean; checks: Record<string, Check> }

export default function App() {
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/health/ready')
      .then((r) => r.json())
      .then(setReadiness)
      .catch((e: unknown) => setError(String(e)))
  }, [])

  return (
    <main className="shell">
      <h1>دستیار نجات مستندات لیارا</h1>
      <p className="lead">
        اسکلت اولیه‌ی سرویس بالا است. وضعیت آمادگی سرویس‌ها در ادامه آمده است.
      </p>
      {error && <p role="alert">خطا در دریافت وضعیت: {error}</p>}
      {readiness && (
        <ul className="checks">
          {Object.entries(readiness.checks).map(([name, check]) => (
            <li key={name}>
              <code>{name}</code> — {check.ok ? 'سالم' : `ناسالم (${check.reason ?? 'نامشخص'})`}
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
