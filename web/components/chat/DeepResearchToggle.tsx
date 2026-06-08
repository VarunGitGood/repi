"use client"

import { Sparkles } from "lucide-react"
import { cn } from "@/lib/utils"

interface DeepResearchToggleProps {
  on: boolean
  onChange: (next: boolean) => void
}

/**
 * Sticky on/off pill — when ON, the next user message routes to /investigate
 * (full ReAct loop, live step stream). When OFF, /chat (single-shot RAG).
 *
 * Sticky like Claude Extended Thinking or OpenAI Deep Research: stays in
 * whichever position the user left it across turns until clicked off.
 * Persisted to localStorage in the parent so a refresh doesn't surprise the
 * user.
 */
export function DeepResearchToggle({ on, onChange }: DeepResearchToggleProps) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={() => onChange(!on)}
      title={
        on
          ? "Deep Research is ON — next message runs a full multi-step investigation"
          : "Deep Research is OFF — next message uses fast single-shot RAG"
      }
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
        on
          ? "border-primary bg-primary/10 text-primary"
          : "border-border bg-background text-muted-foreground hover:bg-muted",
      )}
    >
      <Sparkles className={cn("h-3.5 w-3.5", on && "fill-primary")} />
      Deep Research {on ? "on" : "off"}
    </button>
  )
}
