"use client"

import { motion } from "framer-motion"
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Loader2, Play, Sparkles } from "lucide-react"

export const DEMO_QUERY =
  "Investigate the gateway service incident between 2026-06-10 02:14 UTC and 2026-06-10 02:48 UTC. Users disconnected and saw timeouts. Find the root cause across all services."

interface InvestigationStepProps {
  projectId: string
  onStart: () => string | null
  done: boolean
  /** Card is docked to the corner while the stream runs in the dashboard. */
  docked?: boolean
}

/**
 * Headliner step. Kicks off the real /investigate call through the parent
 * callback on mount (once projectId is hydrated) and lets the dashboard
 * underneath render the actual SSE stream. A manual "Start" button is the
 * fallback path if the auto-start ever silently misses (Strict Mode, stale
 * bundle, slow project hydration).
 */
export function InvestigationStep({ projectId, onStart, done, docked }: InvestigationStepProps) {
  const [phase, setPhase] = useState<"waiting" | "starting" | "streaming">("waiting")
  const startedRef = useRef(false)

  function trigger() {
    if (startedRef.current) return
    if (!projectId) return
    startedRef.current = true
    setPhase("starting")
    onStart()
    // The parent's fire-and-forget async finishes microseconds later; the
    // streaming state is driven by `done` flipping from the parent.
    requestAnimationFrame(() => setPhase("streaming"))
  }

  useEffect(() => {
    trigger()
    // Re-run when projectId or onStart hydrates. The ref keeps this idempotent
    // across React Strict Mode's double-mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, onStart])

  // Docked: card is parked in the corner; the real stream renders in the
  // dashboard. Keep this panel compact — a status line, nothing that competes.
  if (docked) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" />
          <span className="text-sm font-semibold">Deep investigation</span>
          <Badge variant={done ? "default" : "outline"} className="text-[10px] ml-auto">
            {done ? "done" : "running"}
          </Badge>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {done ? (
            <Play className="size-3.5 text-emerald-500 shrink-0" />
          ) : (
            <Loader2 className="size-3.5 animate-spin text-primary shrink-0" />
          )}
          <span className="text-muted-foreground">
            {done
              ? "RCA compiled — shown in the dashboard. Advancing to evals…"
              : "Agent is gathering evidence in the dashboard behind this panel →"}
          </span>
        </div>
      </div>
    )
  }

  const status =
    done
      ? "RCA compiled. Inspect the propagation chain in the dashboard behind this card."
      : phase === "waiting"
      ? !projectId
        ? "Resolving Demo project…"
        : "Ready to start."
      : phase === "starting"
      ? "Starting investigation…"
      : "Streaming ReAct steps. Next unlocks when the agent compiles its answer."

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold tracking-tight flex items-center gap-2">
          <Sparkles className="size-4 text-primary" />
          Deep investigation
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          The agent gets a symptom + time window. It must sweep services, form and test hypotheses,
          then compile an RCA. All visible in the dashboard behind this card.
        </p>
      </div>

      <div className="rounded-lg border bg-background/60 p-3 space-y-2">
        <div className="text-[10px] uppercase tracking-widest font-bold text-muted-foreground">
          Locked query
        </div>
        <p className="font-mono text-xs leading-relaxed">&ldquo;{DEMO_QUERY}&rdquo;</p>
        <div className="flex items-center gap-2 pt-1 flex-wrap">
          <Badge variant="outline" className="text-[10px]">project: Demo</Badge>
          <Badge variant="outline" className="text-[10px]">dataset: Discord gateway cascade</Badge>
          <Badge variant="outline" className="text-[10px]">model: deepseek-v4-flash</Badge>
        </div>
      </div>

      <motion.div
        initial={false}
        animate={{ opacity: 1 }}
        className="rounded-lg border bg-muted/40 px-3 py-2 text-xs flex items-center gap-2"
      >
        {done ? (
          <Play className="size-3.5 text-emerald-500" />
        ) : phase === "waiting" ? (
          <Play className="size-3.5 text-muted-foreground" />
        ) : (
          <Loader2 className="size-3.5 animate-spin text-primary" />
        )}
        <span className={done ? "text-foreground" : "text-muted-foreground"}>{status}</span>
      </motion.div>

      {!done && phase !== "streaming" && (
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={trigger} disabled={!projectId}>
            <Play className="size-3.5" /> Start now
          </Button>
          <span className="text-[11px] text-muted-foreground">
            Auto-start fires on mount; click if it didn&apos;t.
          </span>
        </div>
      )}

      {!done && phase === "streaming" && (
        <p className="text-[11px] text-muted-foreground">
          Tip: phase badge in the chat shows{" "}
          <code className="font-mono">gathering → compiling → done</code>.
        </p>
      )}
    </div>
  )
}
