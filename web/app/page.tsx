"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { API_BASE, api } from "@/lib/api"
import { ChatInput } from "@/components/chat/ChatInput"
import { ChatMessageView, ChatMessageProps } from "@/components/chat/ChatMessage"
import { ConversationSidebar } from "@/components/conversations/ConversationSidebar"
import { InvestigationStepCard } from "@/components/investigation-step"
import { Step, useSSE } from "@/lib/sse"
import { Badge } from "@/components/ui/badge"
import { Sparkles } from "lucide-react"
import { toast } from "sonner"

const DR_KEY = "repi.deepResearch"

// Local transcript model. `mode` discriminates chat vs investigate so we can
// render the right component inline. Investigation turns carry an
// investigationId; the SSE stream is mounted via <InvestigateTurnView />.
// `finalAnswer` is populated when the investigation's SSE `done` event fires —
// kept on the parent's state so the next /chat turn can include it as history
// context (lite contextual chat: see `buildChatHistory`).
type Turn =
  | ({ mode: "chat" } & ChatMessageProps)
  | {
      mode: "investigate"
      id: string
      investigationId: string
      query: string
      finalAnswer?: string
    }

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

export default function HomePage() {
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [deepResearch, setDeepResearch] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const [sidebarRefresh, setSidebarRefresh] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)

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

  // Auto-scroll to bottom on new content.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [turns])

  // Load an existing conversation's transcript from the API.
  const loadConversation = useCallback(async (id: string | null) => {
    setConversationId(id)
    if (!id) {
      setTurns([])
      return
    }
    try {
      const detail = await api.conversations.get(id)
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
        const res = await api.investigations.create(query, conversationId ?? undefined)
        if (!conversationId && res.conversation_id) {
          setConversationId(res.conversation_id)
        }
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

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <ConversationSidebar
        activeId={conversationId}
        onSelect={loadConversation}
        refreshKey={sidebarRefresh}
      />
      <main className="flex-1 flex flex-col">
        <div ref={scrollRef} className="flex-1 overflow-y-auto py-6 space-y-4">
          {empty ? (
            <div className="h-full flex flex-col items-center justify-center text-center px-4">
              <div className="size-12 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
                <Sparkles className="size-6 text-primary" />
              </div>
              <h1 className="text-2xl font-semibold tracking-tight mb-1">Chat with your logs</h1>
              <p className="text-muted-foreground text-sm max-w-md">
                Hybrid retrieval over your ingested logs surfaces a chronological{" "}
                <span className="font-medium text-foreground">timeline</span> and the{" "}
                <span className="font-medium text-foreground">event clusters</span> behind your
                question. Toggle{" "}
                <span className="font-medium text-foreground">Deep Research</span> for a
                full autonomous root-cause investigation.
              </p>
            </div>
          ) : (
            turns.map((t, i) =>
              t.mode === "chat" ? (
                <ChatMessageView
                  key={i}
                  {...t}
                  onInvestigateDeeper={(q) => {
                    // handleSend reads its second arg as the deep-research
                    // decision (not React state) — so the setDeepResearch
                    // call below is purely for UI sync (the toggle visually
                    // moves), not a precondition for the routing. Order
                    // doesn't matter; setState's asynchrony doesn't race.
                    setDeepResearch(true)
                    handleSend(q, true)
                  }}
                />
              ) : (
                <InvestigateTurnView
                  key={t.id}
                  investigationId={t.investigationId}
                  alreadyHoisted={!!t.finalAnswer}
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
        <ChatInput
          deepResearch={deepResearch}
          onDeepResearchChange={setDeepResearch}
          onSend={handleSend}
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
}

function InvestigateTurnView({ investigationId, alreadyHoisted, onComplete }: InvestigateTurnViewProps) {
  const streamUrl = `${API_BASE}/investigations/${investigationId}/stream`
  const { steps, answer, error, done, clarificationQuestion, phase } = useSSE(streamUrl)

  // Hoist the final answer into the parent's turns state once, so the next
  // /chat turn can include it as history context.
  useEffect(() => {
    if (done && answer && !alreadyHoisted) onComplete(answer)
  }, [done, answer, alreadyHoisted, onComplete])

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
          {steps.map((s: Step) => (
            <InvestigationStepCard key={s.step_number} step={s} />
          ))}
        </div>
        {answer && (
          <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm whitespace-pre-wrap">
            {answer
              .replace(/\s*\[chunk:[^\]]+\]/gi, "")
              .replace(/\s*\[chunk_id:[^\]]+\]/gi, "")}
          </div>
        )}
        {error && (
          <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
