"use client"

import { useParams } from "next/navigation"
import { useCallback } from "react"
import { useSSE, Step, InvestigationPhase, InvestigationStats } from "@/lib/sse"
import { InvestigationStepCard } from "@/components/investigation-step"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { AlertCircle, CheckCircle2, Search, ShieldCheck } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { StructuredAnswerView } from "@/components/structured-answer"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Spinner } from "@/components/ui/spinner"
import { statusBadgeProps } from "@/lib/status"
import { cn } from "@/lib/utils"
import { toast } from "sonner"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

// Statuses where the SSE stream is not useful: the run is over, or no events
// will arrive without further user action. `awaiting_clarification` is NOT in
// here — the stream emits the clarification_request event immediately and then
// closes; after the user submits a clarify reply, the REST refetch flips status
// to running and the stream reconnects.
const TERMINAL_STATUSES = new Set(["completed", "failed"]);

type RestState = {
  loading: boolean;
  status: string | null;
  steps: Step[];
  answer: string | null;
  stats: InvestigationStats | null;
  pendingQuestion: string | null;
  error: string | null;
};

export default function InvestigationDetailPage() {
  const { id } = useParams()
  const [rest, setRest] = useState<RestState>({
    loading: true,
    status: null,
    steps: [],
    answer: null,
    stats: null,
    pendingQuestion: null,
    error: null,
  })

  const fetchRest = useCallback(async () => {
    if (!id) return
    try {
      const data = await api.investigations.get(id as string)
      setRest({
        loading: false,
        status: data.status,
        steps: (data.steps ?? []).map((s: any) => ({
          step_number: s.step_number,
          thought: s.thought,
          action: s.action ?? undefined,
          observation: s.observation ?? undefined,
          kind: s.kind ?? null,
        })),
        answer: data.answer ?? null,
        stats: data.stats ?? null,
        pendingQuestion: data.pending_question ?? null,
        error: null,
      })
    } catch (err: any) {
      setRest((r) => ({ ...r, loading: false, error: err.message }))
    }
  }, [id])

  useEffect(() => {
    fetchRest()
  }, [fetchRest])

  // Only open SSE for investigations that are still progressing. Replayed
  // streams trigger a spurious `onerror` when the server closes cleanly
  // (EventSource interprets close as failure), so for terminal states we
  // render directly from REST.
  const shouldStream = !rest.loading && rest.status !== null && !TERMINAL_STATUSES.has(rest.status)
  const streamUrl = shouldStream && id ? `${API_BASE}/investigations/${id}/stream` : null
  const sse = useSSE(streamUrl)

  const steps: Step[] = shouldStream ? sse.steps : rest.steps
  const answer = shouldStream ? sse.answer : rest.answer
  const error = shouldStream ? sse.error : rest.error
  const done = shouldStream ? sse.done : true
  const clarificationQuestion = shouldStream ? sse.clarificationQuestion : rest.pendingQuestion
  const awaitingClarification = shouldStream
    ? sse.awaitingClarification
    : rest.status === "awaiting_clarification"
  const phase: InvestigationPhase | null = shouldStream
    ? sse.phase
    : rest.status === "completed" || rest.status === "failed"
      ? "done"
      : null
  const stats = shouldStream ? sse.stats : rest.stats

  const bottomRef = useRef<HTMLDivElement>(null)
  const [reply, setReply] = useState("")
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!done) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [steps, done, awaitingClarification])

  // Live-stream errors (connection lost during a running investigation) deserve
  // an immediate toast — Alert below stays for persistence, toast catches the
  // user's attention if they're scrolled away.
  useEffect(() => {
    if (shouldStream && sse.error) {
      toast.error(sse.error)
    }
  }, [shouldStream, sse.error])

  const handleClarify = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!reply.trim() || submitting) return

    setSubmitting(true)
    try {
      await api.investigations.clarify(id as string, reply)
      setReply("")
      toast.success("Clarification sent. Investigation resuming...")
      // Re-fetch so rest.status transitions from awaiting_clarification → running.
      // That flips shouldStream, which mounts a fresh SSE connection to pick up
      // the resumed run.
      await fetchRest()
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (!id) return null

  if (rest.loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
        <Spinner size="lg" label="Loading investigation..." />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full max-w-4xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="mb-8 space-y-4">
        <div className="flex items-center justify-between">
          <Badge variant="outline" className="text-muted-foreground uppercase tracking-wider text-[10px]">
            Investigation ID: {id.toString().slice(0, 8)}...
          </Badge>
          <div className="flex items-center gap-2">
            {!done && !awaitingClarification ? (
              <div className="flex items-center gap-2 text-sm text-primary animate-pulse">
                <Spinner size="sm" />
                <span>
                  {phase === "compiling"
                    ? "Compiling answer..."
                    : phase === "gathering"
                      ? "Gathering evidence..."
                      : "Investigation in progress..."}
                </span>
              </div>
            ) : awaitingClarification ? (
              (() => {
                const b = statusBadgeProps("awaiting_clarification")
                return (
                  <Badge variant={b.variant} className={cn("flex items-center gap-1 animate-pulse", b.className)}>
                    <Spinner size="sm" /> Awaiting Clarification
                  </Badge>
                )
              })()
            ) : error ? (
              (() => {
                const b = statusBadgeProps("failed")
                return (
                  <Badge variant={b.variant} className={cn("flex items-center gap-1", b.className)}>
                    <AlertCircle className="h-3 w-3" /> Failed
                  </Badge>
                )
              })()
            ) : (
              (() => {
                const b = statusBadgeProps("completed")
                return (
                  <Badge variant={b.variant} className={cn("flex items-center gap-1", b.className)}>
                    <CheckCircle2 className="h-3 w-3" /> Completed
                  </Badge>
                )
              })()
            )}
          </div>
        </div>
      </div>

      {/* Phase indicator strip */}
      {!awaitingClarification && (phase || done) && (
        <div className="mb-6 flex items-center gap-3 text-xs">
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border ${
            phase === "gathering"
              ? "border-primary/40 bg-primary/10 text-primary"
              : phase === "compiling" || phase === "done" || done
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                : "border-border text-muted-foreground"
          }`}>
            {phase === "gathering" && !done ? (
              <Spinner size="sm" />
            ) : (
              <CheckCircle2 className="h-3 w-3" />
            )}
            <span>Gathering evidence</span>
          </div>
          <div className="h-px flex-1 bg-border" />
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border ${
            phase === "compiling"
              ? "border-violet-500/40 bg-violet-500/10 text-violet-400"
              : phase === "done" || done
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                : "border-border text-muted-foreground"
          }`}>
            {phase === "compiling" ? (
              <Spinner size="sm" />
            ) : phase === "done" || done ? (
              <CheckCircle2 className="h-3 w-3" />
            ) : (
              <ShieldCheck className="h-3 w-3" />
            )}
            <span>Compiling answer</span>
          </div>
        </div>
      )}

      <Separator className="mb-8" />

      {/* Steps List */}
      <div className="flex-1 space-y-2 pb-20">
        {steps.length === 0 && !done && !error && (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground space-y-4">
            <Search className="h-12 w-12 animate-pulse" />
            <p>Initializing ReAct loop...</p>
          </div>
        )}

        {steps.map((step) => (
          <InvestigationStepCard key={step.step_number} step={step} />
        ))}

        {/* Final Answer */}
        {answer && (
          <div className="mt-12 animate-in fade-in slide-in-from-bottom-4 duration-1000">
            <div className="rounded-xl border bg-card p-8 shadow-md ring-1 ring-primary/20 backdrop-blur-sm">
              <div className="flex items-center gap-2 mb-6 text-primary font-bold border-b border-white/5 pb-4">
                <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                   <ShieldCheck className="h-5 w-5" />
                </div>
                <h3 className="text-lg">Investigation Report</h3>
              </div>
              <StructuredAnswerView data={answer} />
            </div>
          </div>
        )}

        {/* Run stats */}
        {stats && done && (
          <div className="mt-4 text-xs text-muted-foreground grid grid-cols-2 sm:grid-cols-4 gap-3 px-2">
            <div>
              <div className="font-bold text-foreground/70 uppercase tracking-wider text-[10px]">Iterations</div>
              <div>{stats.iterations_used ?? 0}</div>
            </div>
            <div>
              <div className="font-bold text-foreground/70 uppercase tracking-wider text-[10px]">Reflections</div>
              <div>{stats.reflections_used ?? 0}</div>
            </div>
            {stats.chunks_gathered !== undefined && (
              <div>
                <div className="font-bold text-foreground/70 uppercase tracking-wider text-[10px]">Chunks gathered</div>
                <div>{stats.chunks_gathered}</div>
              </div>
            )}
            {stats.compile_source && (
              <div>
                <div className="font-bold text-foreground/70 uppercase tracking-wider text-[10px]">Compile source</div>
                <div>{stats.compile_source}</div>
              </div>
            )}
            {stats.tools_called && stats.tools_called.length > 0 && (
              <div className="col-span-2 sm:col-span-4">
                <div className="font-bold text-foreground/70 uppercase tracking-wider text-[10px]">Tools called</div>
                <div className="font-mono">{stats.tools_called.join(", ")}</div>
              </div>
            )}
            {stats.gathering_exit_reason && (
              <div className="col-span-2 sm:col-span-4">
                <div className="font-bold text-foreground/70 uppercase tracking-wider text-[10px]">Gathering exit</div>
                <div className="font-mono">{stats.gathering_exit_reason}</div>
              </div>
            )}
          </div>
        )}

        {/* Clarification Form */}
        {awaitingClarification && clarificationQuestion && (
          <div className="mt-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
             <Card className="border-amber-500/50 bg-amber-500/5 backdrop-blur-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold flex items-center gap-2 text-amber-500">
                  <AlertCircle className="h-4 w-4" />
                  Clarification Required
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm text-foreground/90 italic">
                  &quot;{clarificationQuestion}&quot;
                </p>
                <form onSubmit={handleClarify} className="flex gap-2">
                  <Input
                    placeholder="Your reply..."
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    className="flex-1 bg-background/50"
                  />
                  <Button type="submit" disabled={!reply.trim() || submitting} size="sm" className="bg-amber-500 hover:bg-amber-600 text-black font-bold">
                    {submitting ? <Spinner size="sm" /> : "Resume"}
                  </Button>
                </form>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Error State */}
        {error && (
          <Alert variant="destructive" className="mt-8">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div ref={bottomRef} className="h-1" />
      </div>
    </div>
  )
}
