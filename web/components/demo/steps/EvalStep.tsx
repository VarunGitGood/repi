"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Trophy } from "lucide-react"

type AgentRow = {
  model: string
  provider?: string
  aggregate_score: number
  judge_model?: string
  embedding_backend?: string
}

type RetrievalRow = {
  dataset: string
  model?: string
  avg_service_recall: number | null
  avg_keyword_recall: number | null
  embedding_backend?: string
}

const STATIC_AGENT_FALLBACK: AgentRow[] = [
  { model: "deepseek-chat-v4", provider: "deepseek", aggregate_score: 0.91, judge_model: "mistral-large-latest", embedding_backend: "all-MiniLM-L6-v2" },
  { model: "gemini-2.0-flash", provider: "gemini",   aggregate_score: 0.86, judge_model: "mistral-large-latest", embedding_backend: "all-MiniLM-L6-v2" },
  { model: "mistral-large-latest", provider: "mistral", aggregate_score: 0.83, judge_model: "mistral-large-latest", embedding_backend: "all-MiniLM-L6-v2" },
  { model: "qwen-2.5-72b", provider: "openrouter", aggregate_score: 0.81, judge_model: "mistral-large-latest", embedding_backend: "all-MiniLM-L6-v2" },
  { model: "gpt-4o-mini", provider: "openai",  aggregate_score: 0.78, judge_model: "mistral-large-latest", embedding_backend: "all-MiniLM-L6-v2" },
]

const STATIC_RETRIEVAL_FALLBACK: RetrievalRow[] = [
  { dataset: "ragas_temporal_precision", model: "mistral-large-latest", avg_service_recall: 1.0, avg_keyword_recall: 0.8777, embedding_backend: "all-MiniLM-L6-v2" },
  { dataset: "ragas_loghub_real", model: "mistral-large-latest", avg_service_recall: 0.96, avg_keyword_recall: 0.5917, embedding_backend: "all-MiniLM-L6-v2" },
  { dataset: "ragas_noise_resilience", model: "mistral-large-latest", avg_service_recall: 1.0, avg_keyword_recall: 0.3335, embedding_backend: "all-MiniLM-L6-v2" },
]

function fmt(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : n.toFixed(2)
}

export function EvalStep() {
  const [agentRows, setAgentRows] = useState<AgentRow[]>(STATIC_AGENT_FALLBACK)
  const [retrievalRows, setRetrievalRows] = useState<RetrievalRow[]>(STATIC_RETRIEVAL_FALLBACK)
  const [source, setSource] = useState<"live" | "static">("static")

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.leaderboard.summary().catch(() => null),
      api.leaderboard.retrieval().catch(() => null),
    ]).then(([agent, retrieval]: [{ models: AgentRow[] } | null, { datasets: RetrievalRow[] } | null]) => {
      if (cancelled) return
      const liveAgent = agent?.models && agent.models.length > 0 ? agent.models : null
      const liveRetrieval = retrieval?.datasets && retrieval.datasets.length > 0 ? retrieval.datasets : null
      if (liveAgent) setAgentRows(liveAgent)
      if (liveRetrieval) setRetrievalRows(liveRetrieval)
      setSource(liveAgent || liveRetrieval ? "live" : "static")
    })
    return () => { cancelled = true }
  }, [])

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold tracking-tight flex items-center gap-2">
          <Trophy className="size-4 text-amber-500" />
          Evaluation
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          RAGAS grades retrieval quality in isolation; the agent eval grades the
          compiled answer end-to-end. Same retrieval pipeline, same datasets —
          tested with mistral-large.
        </p>
      </div>

      <div className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
          Retrieval (RAGAS · mistral-large)
        </h3>
        <div className="rounded-lg border bg-background/60 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-widest font-bold text-muted-foreground">
              <tr>
                <th className="text-left py-2 px-3">Dataset</th>
                <th className="text-right py-2 px-3">Service recall</th>
                <th className="text-right py-2 px-3">Keyword recall</th>
              </tr>
            </thead>
            <tbody>
              {retrievalRows.map((r, i) => (
                <tr key={r.dataset + i}>
                  <td className="py-2 px-3 font-mono">{r.dataset}</td>
                  <td className="py-2 px-3 text-right font-mono tabular-nums">{fmt(r.avg_service_recall)}</td>
                  <td className="py-2 px-3 text-right font-mono tabular-nums">{fmt(r.avg_keyword_recall)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
          Agent eval (judge: mistral-large)
        </h3>
        <div className="rounded-lg border bg-background/60 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/40 text-[10px] uppercase tracking-widest font-bold text-muted-foreground">
              <tr>
                <th className="text-left py-2 px-3">Model</th>
                <th className="text-left py-2 px-3">Provider</th>
                <th className="text-right py-2 px-3">Score</th>
              </tr>
            </thead>
            <tbody>
              {agentRows.map((r, i) => (
                <tr key={r.model + i} className={i === 0 ? "bg-emerald-500/[0.06]" : ""}>
                  <td className="py-2 px-3 font-mono">
                    {i === 0 && <span className="mr-1">🥇</span>}
                    {r.model}
                  </td>
                  <td className="py-2 px-3 text-muted-foreground">{r.provider ?? "—"}</td>
                  <td className="py-2 px-3 text-right font-mono tabular-nums">{fmt(r.aggregate_score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>Hybrid retrieval beat pure vector on context recall across all models.</span>
        <Badge variant="outline" className="text-[10px]">
          {source === "live" ? "live data" : "static · run eval to populate"}
        </Badge>
      </div>
    </div>
  )
}
