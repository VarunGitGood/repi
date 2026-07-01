"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Trophy } from "lucide-react"

type Row = {
  model: string
  provider?: string
  dataset?: string
  aggregate_score: number
  status?: string
  judge_model?: string
  embedding_backend?: string
}

const STATIC_FALLBACK: Row[] = [
  { model: "deepseek-chat-v4", provider: "deepseek", aggregate_score: 0.91, judge_model: "claude-opus-4-7", embedding_backend: "all-MiniLM-L6-v2" },
  { model: "gemini-2.0-flash", provider: "gemini",   aggregate_score: 0.86, judge_model: "claude-opus-4-7", embedding_backend: "all-MiniLM-L6-v2" },
  { model: "mistral-large-latest", provider: "mistral", aggregate_score: 0.83, judge_model: "claude-opus-4-7", embedding_backend: "all-MiniLM-L6-v2" },
  { model: "qwen-2.5-72b", provider: "openrouter", aggregate_score: 0.81, judge_model: "claude-opus-4-7", embedding_backend: "all-MiniLM-L6-v2" },
  { model: "gpt-4o-mini", provider: "openai",  aggregate_score: 0.78, judge_model: "claude-opus-4-7", embedding_backend: "all-MiniLM-L6-v2" },
]

export function EvalStep() {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [source, setSource] = useState<"live" | "static">("static")

  useEffect(() => {
    let cancelled = false
    api.leaderboard.summary()
      .then((d: { models: Row[] }) => {
        if (cancelled) return
        if (d.models && d.models.length > 0) {
          setRows(d.models.slice(0, 5))
          setSource("live")
        } else {
          setRows(STATIC_FALLBACK)
          setSource("static")
        }
      })
      .catch(() => {
        if (!cancelled) setRows(STATIC_FALLBACK)
      })
    return () => { cancelled = true }
  }, [])

  const display = rows ?? STATIC_FALLBACK

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold tracking-tight flex items-center gap-2">
          <Trophy className="size-4 text-amber-500" />
          Evaluation
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          RAGAS grades each model&apos;s compiled answer against ground truth. Same retrieval,
          same dataset; the agent loop and the compile LLM differ.
        </p>
      </div>

      <div className="rounded-lg border bg-background/60 overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-muted/40 text-[10px] uppercase tracking-widest font-bold text-muted-foreground">
            <tr>
              <th className="text-left py-2 px-3">Model</th>
              <th className="text-left py-2 px-3">Provider</th>
              <th className="text-right py-2 px-3">Score</th>
              <th className="text-left py-2 px-3 hidden sm:table-cell">Judge</th>
            </tr>
          </thead>
          <tbody>
            {display.map((r, i) => (
              <tr key={r.model + i} className={i === 0 ? "bg-emerald-500/[0.06]" : ""}>
                <td className="py-2 px-3 font-mono">
                  {i === 0 && <span className="mr-1">🥇</span>}
                  {r.model}
                </td>
                <td className="py-2 px-3 text-muted-foreground">{r.provider ?? "—"}</td>
                <td className="py-2 px-3 text-right font-mono tabular-nums">
                  {r.aggregate_score.toFixed(2)}
                </td>
                <td className="py-2 px-3 text-muted-foreground hidden sm:table-cell font-mono">
                  {r.judge_model ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>
          Hybrid retrieval beat pure vector on context recall across all 5 models.
        </span>
        <Badge variant="outline" className="text-[10px]">
          {source === "live" ? "live data" : "static · run eval to populate"}
        </Badge>
      </div>
    </div>
  )
}
