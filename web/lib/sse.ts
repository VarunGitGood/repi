"use client"

import { useState, useEffect, useCallback } from "react"

export type StepKind = null | "reflection" | "signal" | "compile"

export interface Step {
  step_number: number
  thought: string
  action?: {
    tool: string
    args: any
  }
  observation?: any
  kind?: StepKind
}

export type InvestigationPhase = "gathering" | "compiling" | "done"

export interface InvestigationStats {
  iterations_used?: number
  reflections_used?: number
  chunks_gathered?: number
  tools_called?: string[]
  compile_source?: string
  compile_attempts?: number
  floor_adjustments?: string[]
  gathering_exit_reason?: string
}

export function useSSE(url: string | null) {
  const [steps, setSteps] = useState<Step[]>([])
  const [answer, setAnswer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [clarificationQuestion, setClarificationQuestion] = useState<string | null>(null)
  const [awaitingClarification, setAwaitingClarification] = useState(false)
  const [phase, setPhase] = useState<InvestigationPhase | null>(null)
  const [stats, setStats] = useState<InvestigationStats | null>(null)

  const connect = useCallback(() => {
    if (!url) return

    setSteps([])
    setAnswer(null)
    setError(null)
    setDone(false)
    setClarificationQuestion(null)
    setAwaitingClarification(false)
    setPhase(null)
    setStats(null)

    const eventSource = new EventSource(url)

    eventSource.onmessage = (event) => {
      const { type, data } = JSON.parse(event.data)

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
        setDone(true)
        eventSource.close()
      } else if (type === "clarification_request") {
        setClarificationQuestion(data.question)
        setAwaitingClarification(true)
        setDone(false) // Stay open for more steps later
      } else if (type === "error") {
        setError(data.message)
        setDone(true)
        eventSource.close()
      }
    }

    eventSource.onerror = (err) => {
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
