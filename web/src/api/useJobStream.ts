/**
 * Follow one answering job to completion.
 *
 * `EventSource` is used rather than a hand-rolled fetch reader because the
 * browser already implements exactly the reconnection contract the server was
 * built for: it remembers the last `id:` it saw and replays it as
 * `Last-Event-ID` on reconnect, which the API turns into a resume offset. A
 * dropped connection therefore continues rather than restarts, with no retry
 * logic of our own.
 */

import { useEffect, useRef, useState } from 'react'
import { jobEventsUrl } from './client'
import type {
  Citation,
  DeltaEvent,
  ErrorEvent as JobErrorEvent,
  FinalEvent,
  JobStatus,
  StatusEvent,
  TraceEvent,
} from './types'

export type StreamState = {
  status: JobStatus
  /** Answer text accumulated so far. Grows as `delta` entries arrive. */
  answer: string
  /** Search steps the agent has taken so far, in order. */
  trace: TraceEvent[]
  citations: Citation[]
  /** Set only when the job reached a terminal failure. */
  errorCode: string | null
  errorMessage: string | null
  needsClarification: boolean
  attempt: number
  done: boolean
}

const INITIAL: StreamState = {
  status: 'queued',
  answer: '',
  trace: [],
  citations: [],
  errorCode: null,
  errorMessage: null,
  needsClarification: false,
  attempt: 0,
  done: false,
}

export function useJobStream(jobId: string | null): StreamState {
  const [state, setState] = useState<StreamState>(INITIAL)
  // Deltas replayed after a reconnect must not be appended twice.
  const seen = useRef<Set<string>>(new Set())

  useEffect(() => {
    if (!jobId) return
    setState(INITIAL)
    seen.current = new Set()

    const source = new EventSource(jobEventsUrl(jobId))

    source.addEventListener('status', (event) => {
      const data = JSON.parse((event as MessageEvent).data) as StatusEvent
      setState((prev) => ({ ...prev, status: data.status, attempt: data.attempt }))
    })

    source.addEventListener('trace', (event) => {
      const message = event as MessageEvent
      // Replayed after a reconnect, exactly like deltas, so the same guard
      // keeps a resumed stream from listing every step twice.
      if (seen.current.has(message.lastEventId)) return
      seen.current.add(message.lastEventId)
      const data = JSON.parse(message.data) as TraceEvent
      setState((prev) => ({ ...prev, trace: [...prev.trace, data] }))
    })

    source.addEventListener('delta', (event) => {
      const message = event as MessageEvent
      if (seen.current.has(message.lastEventId)) return
      seen.current.add(message.lastEventId)
      const data = JSON.parse(message.data) as DeltaEvent
      setState((prev) => ({ ...prev, answer: prev.answer + data.text }))
    })

    source.addEventListener('final', (event) => {
      const data = JSON.parse((event as MessageEvent).data) as FinalEvent
      setState((prev) => ({
        ...prev,
        // The final entry carries the whole checked answer, so it is the
        // authority; the deltas were only there to render it progressively.
        answer: data.answer,
        citations: data.citations,
        needsClarification: data.needs_clarification,
        // An abstention or a reached limit completes with a code attached. It
        // is not a failure, so it never becomes `errorCode`.
        errorMessage: data.message ?? prev.errorMessage,
        status: 'completed',
        done: true,
      }))
      source.close()
    })

    source.addEventListener('error', (event) => {
      const message = event as MessageEvent
      // `EventSource` reuses the `error` event for transport problems, which
      // carry no data. Those are the browser reconnecting — not a job failure.
      if (!message.data) return
      const data = JSON.parse(message.data) as JobErrorEvent
      setState((prev) => ({
        ...prev,
        status: 'failed',
        errorCode: data.error_code,
        errorMessage: data.message,
        done: true,
      }))
      source.close()
    })

    return () => source.close()
  }, [jobId])

  return state
}
