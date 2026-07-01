"use client"

import { motion } from "framer-motion"
import { useEffect, useState } from "react"
import { Check, FileText, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

// Stages a real /ingest call goes through (parser → chunker → embedder → upsert).
// This step is animation-only; data is pre-seeded out of band.
const STAGES = ["parse", "chunk", "embed", "index"] as const
type Stage = (typeof STAGES)[number]

const FILES: { name: string; service: string; lines: number; chunks: number }[] = [
  { name: "read-states-svc.log", service: "read-states-svc", lines: 38, chunks: 14 },
  { name: "gateway.log",          service: "gateway",         lines: 52, chunks: 19 },
  { name: "message-svc.log",      service: "message-svc",     lines: 31, chunks: 11 },
  { name: "presence-svc.log",     service: "presence-svc",    lines: 22, chunks: 8  },
  { name: "cdn-edge.log",         service: "cdn-edge",        lines: 28, chunks: 10 },
]

// 5 files × 4 stages × ~250ms = ~5s; fast enough to feel snappy, slow enough to read.
const STAGE_MS = 220
const FILE_DELAY_MS = 350

function stageLabel(s: Stage) {
  return { parse: "parsing", chunk: "chunking", embed: "embedding", index: "indexed" }[s]
}

export function SeedingStep() {
  // progress[i] = number of stages completed for file i (0..4). 4 = done.
  const [progress, setProgress] = useState<number[]>(() => FILES.map(() => 0))

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = []
    FILES.forEach((_, i) => {
      STAGES.forEach((_, j) => {
        const t = setTimeout(() => {
          setProgress((prev) => {
            const next = [...prev]
            if (next[i] <= j) next[i] = j + 1
            return next
          })
        }, i * FILE_DELAY_MS + (j + 1) * STAGE_MS)
        timers.push(t)
      })
    })
    return () => timers.forEach(clearTimeout)
  }, [])

  const totalChunks = FILES.reduce((acc, f) => acc + f.chunks, 0)
  const ingestedChunks = FILES.reduce(
    (acc, f, i) => acc + (progress[i] >= STAGES.length ? f.chunks : 0),
    0,
  )

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold tracking-tight">Seeding: Discord gateway cascade</h2>
        <p className="text-sm text-muted-foreground mt-1">
          5 services · {FILES.reduce((a, f) => a + f.lines, 0)} log lines · chunked, embedded with
          all-MiniLM-L6-v2, and indexed into pgvector HNSW + ParadeDB BM25.
        </p>
      </div>

      <div className="space-y-1.5 rounded-lg border bg-background/60 p-2 font-mono text-xs">
        {FILES.map((f, i) => {
          const done = progress[i] >= STAGES.length
          const activeStage = Math.max(0, Math.min(progress[i], STAGES.length - 1))
          return (
            <motion.div
              key={f.name}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.08 }}
              className="flex items-center gap-3 rounded-md px-2 py-1.5"
            >
              <FileText className="size-3.5 text-muted-foreground shrink-0" />
              <span className="w-44 truncate text-foreground/85">{f.name}</span>

              <div className="flex-1 flex items-center gap-1">
                {STAGES.map((s, j) => {
                  const reached = progress[i] > j
                  const current = progress[i] === j
                  return (
                    <div
                      key={s}
                      className={cn(
                        "flex-1 h-1 rounded-full transition-colors",
                        reached
                          ? "bg-emerald-500/80"
                          : current
                          ? "bg-primary/50 animate-pulse"
                          : "bg-muted-foreground/15",
                      )}
                    />
                  )
                })}
              </div>

              <span className="w-20 text-right text-muted-foreground tabular-nums">
                {done ? `${f.chunks} chunks` : stageLabel(STAGES[activeStage])}
              </span>

              <div className="w-4 flex justify-center">
                {done ? (
                  <Check className="size-3.5 text-emerald-500" />
                ) : (
                  <Loader2 className="size-3.5 text-muted-foreground animate-spin" />
                )}
              </div>
            </motion.div>
          )
        })}
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Pipeline: <span className="font-mono">parse → chunk → embed → upsert</span>
        </span>
        <span className="font-mono tabular-nums">
          {ingestedChunks}/{totalChunks} chunks
        </span>
      </div>
    </div>
  )
}
