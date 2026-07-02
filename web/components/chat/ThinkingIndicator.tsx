"use client"

import { useEffect, useState } from "react"
import { Spinner } from "@/components/ui/spinner"
import type { InvestigationPhase, Step } from "@/lib/sse"

// Steps only stream in after a tool observation completes, so the gaps
// between them (LLM call + tool call, 10–30s on throttled providers) need
// a contextual status line derived from what the loop is doing.

const TOOL_STATUS: Record<string, string> = {
  search_logs: "Searching logs",
  scan_window: "Scanning the error window",
  get_timeline: "Building a timeline",
  get_service_summary: "Profiling service health",
  find_logs_by_id: "Tracing that identifier",
  done_gathering: "Wrapping up evidence gathering",
}

const THINKING_WORDS = [
  "Thinking",
  "Correlating events",
  "Weighing evidence",
  "Reading log clusters",
  "Forming hypotheses",
  "Drinking water",
  "Taking a deep breath",
  "Crashing out",
  "Praying to the AI gods"
]

function contextLabel(phase: InvestigationPhase | null, lastStep?: Step): string | null {
  if (phase === "done") return null
  if (phase === "compiling") return "Compiling the answer"
  if (phase === "gathering") {
    if (!lastStep) return "Sweeping recent activity"
    if (lastStep.kind === "reflection") return "Stepping back to re-plan"
    const tool = lastStep.action?.tool
    if (tool && TOOL_STATUS[tool]) return `${TOOL_STATUS[tool]} — deciding next move`
    return null // fall through to rotating words
  }
  return "Reading your question"
}

interface ThinkingIndicatorProps {
  phase: InvestigationPhase | null
  lastStep?: Step
  // Stream connection dropped and we're retrying (tab was backgrounded, brief
  // network blip, etc). The investigation keeps running server-side, so this
  // is a quiet status line, not an error.
  reconnecting?: boolean
}

export function ThinkingIndicator({ phase, lastStep, reconnecting }: ThinkingIndicatorProps) {
  const [tick, setTick] = useState(0)

  // Restart the rotation whenever a new step lands, so the contextual label
  // shows first and generic thinking words take over while the gap drags on.
  useEffect(() => {
    setTick(0)
    const id = setInterval(() => setTick((t) => t + 1), 3000)
    return () => clearInterval(id)
  }, [phase, lastStep?.step_number])

  if (reconnecting) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground italic">
        <Spinner size="sm" />
        <span>Reconnecting to stream…</span>
      </div>
    )
  }

  if (lastStep?.kind === "reflection") {
    return null
  }

  const context = contextLabel(phase, lastStep)
  const rotation = context ? [context, ...THINKING_WORDS] : THINKING_WORDS
  const label = rotation[tick % rotation.length]

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground italic">
      <Spinner size="sm" />
      <span>{label}…</span>
    </div>
  )
}
