"use client"

import { motion } from "framer-motion"
import { MessageSquare, Microscope } from "lucide-react"

export function ModesStep() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold tracking-tight">Two modes, same retrieval</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Both share hybrid search (BM25 + pgvector w/ RRF). One answers, one investigates.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <motion.div
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          className="rounded-xl border bg-background/60 p-4 space-y-2"
        >
          <div className="flex items-center gap-2 text-sm font-semibold">
            <MessageSquare className="size-4 text-primary" />
            One-shot RAG
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Ask a question. Retrieve relevant chunks. One LLM call. Cited answer. No tools, no loop.
          </p>
          <p className="text-[11px] text-muted-foreground/70 font-mono pt-1">
            best for: facts (&quot;when did X happen?&quot;)
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, x: 10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.05 }}
          className="rounded-xl border-2 border-primary/50 bg-primary/[0.04] p-4 space-y-2"
        >
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Microscope className="size-4 text-primary" />
            Deep investigation
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Symptom in, RCA out. ReAct loop drives tool calls
            (<code>search_logs</code>, <code>get_timeline</code>, <code>scan_window</code>) until it
            can compile an answer.
          </p>
          <p className="text-[11px] text-muted-foreground/70 font-mono pt-1">
            best for: causes (&quot;why did X happen?&quot;)
          </p>
        </motion.div>
      </div>

      <p className="text-xs text-muted-foreground">
        Next: we&apos;ll kick off a deep investigation against the seeded dataset for you.
      </p>
    </div>
  )
}
