"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import type {
  InvestigationPhase,
  InvestigationStats,
  Step,
  StepKind,
} from "@/lib/types"

export type { InvestigationPhase, InvestigationStats, Step, StepKind }

export function useSSE(url: string | null) {
  const [steps, setSteps] = useState<Step[]>([])
  const [answer, setAnswer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [clarificationQuestion, setClarificationQuestion] = useState<string | null>(null)
  const [awaitingClarification, setAwaitingClarification] = useState(false)
  const [phase, setPhase] = useState<InvestigationPhase | null>(null)
  const [stats, setStats] = useState<InvestigationStats | null>(null)
  // Mirror of `done` readable synchronously inside the EventSource callbacks,
  // which capture state from the connect-time render.
  const doneRef = useRef(false)

  const connect = useCallback(() => {
    if (!url) return

    setSteps([])
    setAnswer(null)
    setError(null)
    doneRef.current = false
    setDone(false)
    setClarificationQuestion(null)
    setAwaitingClarification(false)
    setPhase(null)
    setStats(null)

    const eventSource = new EventSource(url)

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

    eventSource.onerror = (err) => {
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
        return
      }
      console.error("SSE Error:", err)
      setError("Connection to investigation stream lost.")
      setDone(true)
      eventSource.close()
    }

    return () => eventSource.close()
  }, [url])

  useEffect(() => {
    const cleanup = connect()
    return () => {
      if (cleanup) cleanup()
    }
  }, [connect])

  return {
    steps,
    answer,
    error,
    done,
    clarificationQuestion,
    awaitingClarification,
    phase,
    stats,
  }
}
