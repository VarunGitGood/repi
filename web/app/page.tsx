"use client"

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "next/navigation"
import { API_BASE, api } from "@/lib/api"
import { ChatInput } from "@/components/chat/ChatInput"
import { ChatMessageView, ChatMessageProps } from "@/components/chat/ChatMessage"
import { ConversationSidebar } from "@/components/conversations/ConversationSidebar"
import { InvestigationStepCard } from "@/components/investigation-step"
import { ProjectPicker } from "@/components/projects/ProjectPicker"
import { ProjectOverview, type SuggestedAction } from "@/components/projects/ProjectOverview"
import { useSSE } from "@/lib/sse"
import { ThinkingIndicator } from "@/components/chat/ThinkingIndicator"
import { CompiledAnswer } from "@/components/chat/CompiledAnswer"
import { Badge } from "@/components/ui/badge"
import { Sparkles } from "lucide-react"
import { toast } from "sonner"
import type { Step, Turn } from "@/lib/types"
import { DemoTour } from "@/components/demo/DemoTour"
import { DEMO_QUERY } from "@/components/demo/steps/InvestigationStep"

const DEMO_PROJECT_NAME = "Demo"

const DR_KEY = "repi.deepResearch"

// Token-budget proxy: number of recent turns to send to /chat as `history`.
// 6 covers a typical Q&A → followup → followup flow without bloating the prompt.
// No compaction, no summarisation — when it falls off it falls off. The
// `/investigate` path is intentionally stateless and ignores this.
const CHAT_HISTORY_TURNS = 6

// Pull the most recent assistant chat turn's cited chunks so the next /chat
// turn can bias retrieval toward the same service + time envelope. Stream 4
// followup awareness — the backend treats this as a soft hint and never
// overrides explicit intent.
function lastChatChunkIds(turns: Turn[]): string[] {
  for (let i = turns.length - 1; i >= 0; i--) {
    const t = turns[i]
    if (t.mode === "chat" && t.role === "assistant" && t.chunkIds && t.chunkIds.length > 0) {
      return t.chunkIds
    }
  }
  return []
}

function buildChatHistory(turns: Turn[]): { role: "user" | "assistant"; content: string }[] {
  // Treat both chat turns and completed investigation answers as conversation
  // history. An investigation that hasn't produced a final answer yet is
  // skipped (no useful text to feed the model).
  const flat: { role: "user" | "assistant"; content: string }[] = []
  for (const t of turns) {
    if (t.mode === "chat") {
      // Skip the empty placeholder we just pushed for the current turn.
      if (!t.content) continue
      flat.push({ role: t.role, content: t.content })
    } else if (t.mode === "investigate") {
      flat.push({ role: "user", content: t.query })
      if (t.finalAnswer) flat.push({ role: "assistant", content: t.finalAnswer })
    }
  }
  return flat.slice(-CHAT_HISTORY_TURNS)
}

export default function HomePageWrapper() {
  // useSearchParams() requires a Suspense boundary in Next 15 prod builds.
  return (
    <Suspense fallback={null}>
      <HomePage />
    </Suspense>
  )
}

function HomePage() {
  const searchParams = useSearchParams()
  const demoMode = searchParams.get("demo") === "1"
  const [demoInvestigationId, setDemoInvestigationId] = useState<string | null>(null)
  const demoStartedRef = useRef(false)

  const [conversationId, setConversationId] = useState<string | null>(null)
  // Context-before-investigation: every conversation is scoped to a project.
  // null → show the picker (which auto-selects when only one project exists).
  const [project, setProject] = useState<{ id: string; name: string } | null>(null)
  const [deepResearch, setDeepResearch] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const [sidebarRefresh, setSidebarRefresh] = useState(0)
  // Conversation id whose investigation is streaming this session — drives the
  // sidebar's per-row loading spinner. Session-only: cleared when the stream
  // settles or the user switches conversations (not persisted across reload).
  const [activeInvestigatingConvId, setActiveInvestigatingConvId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  // Whether the view should keep itself pinned to the bottom as new content
  // (streaming investigation steps / chat deltas) grows. Flips to false when
  // the user scrolls up to read, so we don't yank them back down.
  const stickToBottom = useRef(true)

  // Demo mode: auto-select (or create) the "Demo" project so the picker is
  // skipped and the dashboard mounts immediately under the tour overlay.
  useEffect(() => {
    if (!demoMode || project) return
    let cancelled = false
    ;(async () => {
      try {
        const list: { id: string; name: string }[] = await api.projects.list()
        let demo = list.find((p) => p.name === DEMO_PROJECT_NAME)
        if (!demo) {
          demo = await api.projects.create(DEMO_PROJECT_NAME)
        }
        if (!cancelled && demo) {
          setProject({ id: demo.id, name: demo.name })
        }
      } catch (e: any) {
        if (!cancelled) toast.error("Demo: could not init project: " + e.message)
      }
    })()
    return () => { cancelled = true }
  }, [demoMode, project])

  // Restore the sticky toggle from localStorage on mount.
  useEffect(() => {
    try {
      const stored = localStorage.getItem(DR_KEY)
      if (stored === "1") setDeepResearch(true)
    } catch {}
  }, [])
  useEffect(() => {
    try { localStorage.setItem(DR_KEY, deepResearch ? "1" : "0") } catch {}
  }, [deepResearch])

  // New turn (the user just sent something, or a transcript loaded) → snap to
  // the bottom and re-arm bottom-sticking.
  useEffect(() => {
    stickToBottom.current = true
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [turns])

  // Follow streaming content (investigation steps / chat deltas) that grows
  // WITHOUT changing `turns`. A ResizeObserver on the content wrapper keeps the
  // view pinned to the bottom, but only while the user is already there.
  useEffect(() => {
    const el = scrollRef.current
    const content = contentRef.current
    if (!el || !content) return
    const ro = new ResizeObserver(() => {
      if (stickToBottom.current) el.scrollTop = el.scrollHeight
    })
    ro.observe(content)
    return () => ro.disconnect()
  }, [])

  // Track whether the user is parked near the bottom; drives `stickToBottom`.
  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    stickToBottom.current = distanceFromBottom < 80
  }

  // Load an existing conversation's transcript from the API.
  const loadConversation = useCallback(async (id: string | null) => {
    setConversationId(id)
    // Switching conversations drops the live stream we were following, so any
    // session-only "investigating" spinner no longer applies.
    setActiveInvestigatingConvId(null)
    if (!id) {
      // New conversation → back to project selection (the picker auto-skips
      // itself when exactly one project exists).
      setProject(null)
      setTurns([])
      return
    }
    try {
      const detail = await api.conversations.get(id)
      setProject(
        detail.project_id
          ? { id: detail.project_id, name: detail.project_name ?? "Project" }
          : null,
      )
      const rendered: Turn[] = detail.turns.map((t: any, idx: number) => {
        if (t.mode === "chat") {
          return {
            mode: "chat" as const,
            role: t.role,
            content: t.content,
            chunkIds: t.chunk_ids,
            confidence: t.confidence,
          }
        }
        return {
          mode: "investigate" as const,
          id: `inv-${idx}-${t.id}`,
          investigationId: t.id,
          query: t.content,
        }
      })
      setTurns(rendered)
    } catch (e: any) {
      toast.error("Could not load conversation: " + e.message)
    }
  }, [])

  // Demo-only: kick off the locked investigation against the Demo project.
  // Idempotent — won't fire a second `/investigate` if we already have an id.
  const startDemoInvestigation = useCallback(() => {
    if (demoStartedRef.current) {
      console.debug("[demo] startDemoInvestigation: already started, id=", demoInvestigationId)
      return demoInvestigationId
    }
    if (!project) {
      console.debug("[demo] startDemoInvestigation: project not loaded yet, deferring")
      return null
    }
    demoStartedRef.current = true
    console.debug("[demo] startDemoInvestigation: firing /investigate for project", project.id)
    ;(async () => {
      try {
        const res = await api.investigations.create(DEMO_QUERY, undefined, project.id)
        console.debug("[demo] /investigate ok:", res)
        setDemoInvestigationId(res.id)
        if (res.conversation_id) {
          setConversationId(res.conversation_id)
          setActiveInvestigatingConvId(res.conversation_id)
        }
        setTurns((prev) => [
          ...prev,
          { mode: "chat", role: "user", content: DEMO_QUERY },
          { mode: "investigate", id: `inv-${res.id}`, investigationId: res.id, query: DEMO_QUERY },
        ])
        setSidebarRefresh((n) => n + 1)
        toast.success("Demo investigation started")
      } catch (e: any) {
        console.error("[demo] /investigate failed:", e)
        toast.error("Demo: investigation failed to start: " + e.message)
        demoStartedRef.current = false
      }
    })()
    return null
  }, [demoInvestigationId, project])

  const demoInvestigationDone = useMemo(
    () =>
      !!demoInvestigationId &&
      turns.some(
        (t) =>
          t.mode === "investigate" &&
          t.investigationId === demoInvestigationId &&
          !!t.finalAnswer,
      ),
    [demoInvestigationId, turns],
  )

  async function handleSend(query: string, dr: boolean) {
    setBusy(true)
    // Optimistic user turn render.
    setTurns((prev) => [
      ...prev,
      { mode: "chat", role: "user", content: query },
    ])

    if (dr) {
      // Toggle ON → kick off a real investigation, embed its SSE stream.
      try {
        const res = await api.investigations.create(query, conversationId ?? undefined, project?.id)
        const convId = res.conversation_id ?? conversationId
        if (!conversationId && res.conversation_id) {
          setConversationId(res.conversation_id)
        }
        // Mark this conversation as investigating so the sidebar shows a spinner
        // on its row until the stream settles (see InvestigateTurnView.onSettled).
        if (convId) setActiveInvestigatingConvId(convId)
        setTurns((prev) => [
          ...prev,
          {
            mode: "investigate",
            id: `inv-${res.id}`,
            investigationId: res.id,
            query,
          },
        ])
        setSidebarRefresh((n) => n + 1)
      } catch (e: any) {
        toast.error("Failed to start investigation: " + e.message)
      } finally {
        setBusy(false)
      }
      return
    }

    // Toggle OFF → /chat SSE. fetch streams the body; parse `data: …\n\n` lines.
    // Send last N turns as history so the server can keep the assistant
    // contextual across followups (lite — no DB lookup, no compaction).
    const history = buildChatHistory(turns)
    const previousChunkIds = lastChatChunkIds(turns)
    try {
      const resp = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          conversation_id: conversationId ?? undefined,
          project_id: project?.id ?? undefined,
          history,
          previous_chunk_ids: previousChunkIds,
        }),
      })
      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status}`)
      }

      // Push a placeholder assistant turn that we mutate in-place as deltas arrive.
      // The placeholder carries a unique pendingId so we can locate it by identity
      // regardless of how the turns array has grown since it was appended.
      const pendingId = `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      const findPending = (arr: Turn[]) =>
        arr.findIndex((t) => t.mode === "chat" && (t as any).pendingId === pendingId)
      setTurns((prev) => [
        ...prev,
        { mode: "chat", role: "assistant", content: "", chunkIds: [], confidence: null, streaming: true, pendingId, query } as any,
      ])

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ""
      let lastConvId: string | null = null
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const blocks = buf.split("\n\n")
        buf = blocks.pop() ?? ""
        for (const block of blocks) {
          if (!block.startsWith("data:")) continue
          const payload = block.slice(5).trim()
          if (!payload) continue
          try {
            const { type, data } = JSON.parse(payload)
            if (data?.conversation_id) lastConvId = data.conversation_id
            if (type === "delta") {
              setTurns((prev) => {
                const idx = findPending(prev)
                if (idx < 0) return prev
                const next = [...prev]
                const cur = next[idx] as any
                next[idx] = { ...cur, content: (cur.content || "") + data.text, streaming: false }
                return next
              })
            } else if (type === "clarify") {
              setTurns((prev) => {
                const idx = findPending(prev)
                if (idx < 0) return prev
                const next = [...prev]
                next[idx] = {
                  mode: "chat",
                  role: "assistant",
                  content: data.question,
                  isClarification: true,
                  confidence: "low",
                  chunkIds: [],
                  pendingId,
                } as any
                return next
              })
            } else if (type === "done") {
              setTurns((prev) => {
                const idx = findPending(prev)
                if (idx < 0) return prev
                const next = [...prev]
                const cur = next[idx] as any
                next[idx] = {
                  ...cur,
                  chunkIds: data.chunk_ids ?? [],
                  confidence: data.confidence ?? null,
                  clusters: data.clusters ?? [],
                  timeline: data.timeline ?? [],
                  citedChunks: data.cited_chunks ?? [],
                  streaming: false,
                }
                return next
              })
            } else if (type === "error") {
              toast.error("Chat error: " + data.message)
            }
          } catch (e) {
            console.error("Failed to parse SSE block", e, block)
          }
        }
      }
      if (lastConvId && !conversationId) {
        setConversationId(lastConvId)
      }
      setSidebarRefresh((n) => n + 1)
    } catch (e: any) {
      toast.error("Chat failed: " + e.message)
    } finally {
      setBusy(false)
    }
  }

  const empty = turns.length === 0

  function handleCommand(command: string) {
    const [cmd, ...args] = command.trim().split(/\s+/)
    if (cmd === "info") {
      const windowArg = args[0]
      setTurns((prev) => [
        ...prev,
        { mode: "chat", role: "user", content: `/${command}` },
        { mode: "command", command: "info", window: windowArg },
      ])
    }
  }

  // Suggested-action chips from the overview: investigate → Deep Research
  // path; chat → normal /chat turn. Both flow through handleSend so the
  // conversation/threading behaviour is identical to typing the query.
  function handleSuggestedAction(action: SuggestedAction) {
    if (action.kind === "investigate") {
      setDeepResearch(true)
      handleSend(action.query, true)
    } else {
      handleSend(action.query, false)
    }
  }

  // New chat, no project yet → step 1 of the flow: pick (or create) a project.
  // Demo mode skips this: the auto-select effect above is resolving the
  // Demo project; render an empty shell with the overlay on top so the user
  // sees the SeedingStep immediately instead of the picker flash.
  if (!conversationId && !project) {
    return (
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <ConversationSidebar
          activeId={conversationId}
          onSelect={loadConversation}
          refreshKey={sidebarRefresh}
        />
        <main className="flex-1 flex flex-col min-h-0">
          {demoMode ? null : (
            <ProjectPicker onSelect={(p) => setProject({ id: p.id, name: p.name })} />
          )}
        </main>
        {demoMode && (
          <DemoTour
            projectId=""
            onStartInvestigation={startDemoInvestigation}
            investigationStarted={!!demoInvestigationId}
            investigationDone={demoInvestigationDone}
          />
        )}
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] overflow-hidden">
      {demoMode && project && (
        <DemoTour
          projectId={project.id}
          onStartInvestigation={startDemoInvestigation}
          investigationStarted={!!demoInvestigationId}
          investigationDone={demoInvestigationDone}
        />
      )}
      <ConversationSidebar
        activeId={conversationId}
        onSelect={loadConversation}
        refreshKey={sidebarRefresh}
        activeInvestigatingId={activeInvestigatingConvId}
      />
      <main className="flex-1 flex flex-col min-h-0">
        <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto">
          <div ref={contentRef} className="py-6 space-y-4">
          {empty ? (
            // Timeline-first landing: no empty chat screen. The overview
            // answers "what happened recently?" before the user types.
            project ? (
              <ProjectOverview
                projectId={project.id}
                projectName={project.name}
                onAction={handleSuggestedAction}
              />
            ) : null
          ) : (
            turns.map((t, i) =>
              t.mode === "chat" ? (
                <ChatMessageView
                  key={i}
                  {...t}
                  onInvestigateDeeper={(q) => {
                    setDeepResearch(true)
                    handleSend(q, true)
                  }}
                />
              ) : t.mode === "command" ? (
                t.command === "info" && project ? (
                  <ProjectOverview
                    key={`cmd-${i}`}
                    projectId={project.id}
                    projectName={project.name}
                    window={t.window}
                    onAction={handleSuggestedAction}
                  />
                ) : null
              ) : (
                <InvestigateTurnView
                  key={t.id}
                  investigationId={t.investigationId}
                  alreadyHoisted={!!t.finalAnswer}
                  onSettled={() => setActiveInvestigatingConvId(null)}
                  onComplete={(finalAnswer) => {
                    setTurns((prev) => {
                      const idx = prev.findIndex(
                        (p) => p.mode === "investigate" && p.id === t.id,
                      )
                      if (idx < 0) return prev
                      const cur = prev[idx]
                      if (cur.mode !== "investigate" || cur.finalAnswer) return prev
                      const next = [...prev]
                      next[idx] = { ...cur, finalAnswer }
                      return next
                    })
                  }}
                />
              ),
            )
          )}
          </div>
        </div>
        <ChatInput
          deepResearch={deepResearch}
          onDeepResearchChange={setDeepResearch}
          onSend={handleSend}
          onCommand={handleCommand}
          busy={busy}
        />
      </main>
    </div>
  )
}

// ── Embedded investigation view ──────────────────────────────────────────────
// Renders the live SSE step stream for an investigation triggered from this
// chat. Reuses the same hook the standalone /investigations/[id] page uses.

interface InvestigateTurnViewProps {
  investigationId: string
  alreadyHoisted: boolean
  onComplete: (finalAnswer: string) => void
  onSettled?: () => void
}

function InvestigateTurnView({ investigationId, alreadyHoisted, onComplete, onSettled }: InvestigateTurnViewProps) {
  const streamUrl = `${API_BASE}/investigations/${investigationId}/stream`
  const { steps, answer, error, done, clarificationQuestion, awaitingClarification, phase } = useSSE(streamUrl)

  // Hoist the final answer into the parent's turns state once, so the next
  // /chat turn can include it as history context.
  useEffect(() => {
    if (done && answer && !alreadyHoisted) onComplete(answer)
  }, [done, answer, alreadyHoisted, onComplete])

  // Stream reached a terminal state (answered, errored, or otherwise done) →
  // let the parent clear the sidebar "investigating" spinner.
  useEffect(() => {
    if (done || error) onSettled?.()
  }, [done, error, onSettled])

  // Renders as the assistant-side response of a chat turn. The user-side
  // bubble is owned by the parent (the optimistic push in handleSend) — this
  // component is purely "what the assistant did to answer."
  return (
    <div className="max-w-3xl mx-auto px-4 flex gap-3 justify-start">
      <div className="flex-shrink-0 size-8 rounded-full bg-primary/10 flex items-center justify-center mt-1">
        <Sparkles className="size-4 text-primary" />
      </div>
      <div className="max-w-[85%] flex-1 rounded-2xl border bg-card/50 p-4 space-y-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Deep Research</span>
          <Badge variant="outline" className="ml-1 text-[10px]">
            {phase ?? (done ? "done" : "starting…")}
          </Badge>
        </div>
        {clarificationQuestion && (
          <div className="rounded-md border bg-muted/40 px-3 py-2 text-xs">
            Awaiting clarification: {clarificationQuestion}
          </div>
        )}
        <div className="space-y-2">
          {steps.map((s: Step, idx: number) => (
            <InvestigationStepCard
              key={s.step_number}
              step={s}
              isActive={idx === steps.length - 1 && !done && !error && !awaitingClarification}
            />
          ))}
        </div>
        {!done && !error && !awaitingClarification && (
          <ThinkingIndicator phase={phase} lastStep={steps[steps.length - 1]} />
        )}
        {answer && <CompiledAnswer answer={answer} />}
        {error && (
          <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
