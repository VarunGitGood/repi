"use client"

import { useState, useEffect, useCallback } from "react"

export interface Step {
  step_number: number
  thought: string
  action?: {
    tool: string
    args: any
  }
  observation?: any
}

export function useSSE(url: string | null) {
  const [steps, setSteps] = useState<Step[]>([])
  const [answer, setAnswer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const connect = useCallback(() => {
    if (!url) return

    setSteps([])
    setAnswer(null)
    setError(null)
    setDone(false)

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
      } else if (type === "done") {
        setAnswer(data.answer)
        setDone(true)
        eventSource.close()
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

  return { steps, answer, error, done }
}
