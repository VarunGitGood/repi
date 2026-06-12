"use client"

import { useEffect, useState } from "react"
import { Spinner } from "@/components/ui/spinner"
import type { InvestigationPhase, Step } from "@/lib/sse"

// Steps only stream in AFTER a tool observation completes, so the gaps
// between them (an LLM call + a tool call, 10–30s on throttled providers)
// previously showed nothing. This fills those gaps with a contextual status
// line derived from what the loop is actually doing.

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
}

export function ThinkingIndicator({ phase, lastStep }: ThinkingIndicatorProps) {
  const [tick, setTick] = useState(0)

  // Restart the rotation whenever a new step lands, so the contextual label
  // shows first and generic thinking words take over while the gap drags on.
  useEffect(() => {
    setTick(0)
    const id = setInterval(() => setTick((t) => t + 1), 3000)
    return () => clearInterval(id)
  }, [phase, lastStep?.step_number])

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
