"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import type {
  InvestigationPhase,
  InvestigationStats,
  Step,
  StepKind,
} from "@/lib/types"

export type { InvestigationPhase, InvestigationStats, Step, StepKind }

// Reconnect backoff once the browser's own EventSource retry gives up
// (readyState goes CLOSED rather than CONNECTING — backgrounded tabs / flaky
// networks close the connection outright rather than leaving it CONNECTING).
// Retries are unbounded: the investigation keeps running server-side
// regardless of the client's connection state, so there is no client-side
// condition under which giving up is correct — only the server's own `done`
// / `error` SSE events are ever treated as terminal (see onmessage below).
// Backoff exponent is capped independently of attempt count so very long
// outages don't grow the delay past RECONNECT_MAX_DELAY_MS.
const RECONNECT_BASE_DELAY_MS = 1000
const RECONNECT_MAX_DELAY_MS = 15000

export function useSSE(url: string | null) {
  const [steps, setSteps] = useState<Step[]>([])
  const [answer, setAnswer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [clarificationQuestion, setClarificationQuestion] = useState<string | null>(null)
  const [awaitingClarification, setAwaitingClarification] = useState(false)
  const [phase, setPhase] = useState<InvestigationPhase | null>(null)
  const [stats, setStats] = useState<InvestigationStats | null>(null)
  // True while we're mid-reconnect (browser retry or our own manual retry)
  // and the investigation hasn't actually failed — UI shows a subtle
  // "reconnecting" hint instead of an error.
  const [reconnecting, setReconnecting] = useState(false)
  // Mirror of `done` readable synchronously inside the EventSource callbacks,
  // which capture state from the connect-time render.
  const doneRef = useRef(false)
  const eventSourceRef = useRef<EventSource | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback((isReconnect = false) => {
    if (!url) return

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    if (!isReconnect) {
      setSteps([])
      setAnswer(null)
      setError(null)
      doneRef.current = false
      setDone(false)
      setClarificationQuestion(null)
      setAwaitingClarification(false)
      setPhase(null)
      setStats(null)
      reconnectAttemptsRef.current = 0
      setReconnecting(false)
    } else {
      setError(null)
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    const eventSource = new EventSource(url)
    eventSourceRef.current = eventSource

    eventSource.onopen = () => {
      reconnectAttemptsRef.current = 0
      setReconnecting(false)
    }

    eventSource.onmessage = (event) => {
      let type: string
      let data: any
      try {
        ;({ type, data } = JSON.parse(event.data))
      } catch {
        // A single malformed frame must not tear down the whole stream.
        console.warn("SSE: dropped unparseable frame", event.data)
        return
      }

      if (type === "step") {
        setSteps((prev) => {
          // Avoid duplicates if replaying
          if (prev.some(s => s.step_number === data.step_number)) {
            return prev
          }
          return [...prev, data]
        })
      } else if (type === "phase_change") {
        setPhase(data.phase)
      } else if (type === "done") {
        setAnswer(data.answer)
        if (data.stats) setStats(data.stats)
        setPhase("done")
        doneRef.current = true
        setDone(true)
        eventSource.close()
      } else if (type === "clarification_request") {
        setClarificationQuestion(data.question)
        setAwaitingClarification(true)
        setDone(false) // Stay open for more steps later
      } else if (type === "error") {
        setError(data.message)
        doneRef.current = true
        setDone(true)
        eventSource.close()
      }
    }

    eventSource.onerror = () => {
      // The server closes the stream once it has sent `done`; the resulting
      // error here is expected — swallow it.
      if (doneRef.current) {
        eventSource.close()
        return
      }
      // readyState === CONNECTING means the browser is auto-reconnecting. The
      // stream endpoint replays prior steps (deduped above) and resumes the
      // loop, so let the retry happen instead of tearing the view down.
      if (eventSource.readyState === EventSource.CONNECTING) {
        console.warn("SSE: transient disconnect, reconnecting…")
        setReconnecting(true)
        return
      }
      // readyState === CLOSED — the browser gave up on its own retry (common
      // when a tab is backgrounded or the network drops outright). The
      // investigation itself keeps running server-side (background task +
      // broadcaster), so retry ourselves with backoff — indefinitely. There
      // is no attempt cap: the server-side investigation doesn't stop just
      // because the client can't reach it right now, so declaring client-side
      // failure here would be a false negative, not a real one.
      eventSource.close()
      reconnectAttemptsRef.current += 1
      setReconnecting(true)
      const delay = Math.min(
        RECONNECT_BASE_DELAY_MS * 2 ** Math.min(reconnectAttemptsRef.current - 1, 4),
        RECONNECT_MAX_DELAY_MS,
      )
      console.warn(`SSE: connection closed, retrying in ${delay}ms (attempt ${reconnectAttemptsRef.current})…`)
      reconnectTimeoutRef.current = setTimeout(() => connect(true), delay)
    }

    return () => {
      eventSource.close()
      eventSourceRef.current = null
    }
  }, [url])

  useEffect(() => {
    const cleanup = connect()

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible" && !doneRef.current && url) {
        const isClosed = !eventSourceRef.current || eventSourceRef.current.readyState === EventSource.CLOSED
        if (isClosed) {
          console.log("SSE: Tab active, reconnecting lost stream...")
          // Fresh retry budget now that the user is actively watching again.
          reconnectAttemptsRef.current = 0
          connect(true)
        }
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityChange)

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      if (cleanup) cleanup()
      document.removeEventListener("visibilitychange", handleVisibilityChange)
    }
  }, [connect, url])

  return {
    steps,
    answer,
    error,
    done,
    clarificationQuestion,
    awaitingClarification,
    phase,
    stats,
    reconnecting,
  }
}
