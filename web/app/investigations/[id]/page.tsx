"use client"

import { useParams } from "next/navigation"
import { useSSE } from "@/lib/sse"
import { InvestigationStepCard } from "@/components/investigation-step"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { AlertCircle, CheckCircle2, Loader2, Search } from "lucide-react"
import ReactMarkdown from "react-markdown"
import { useEffect, useRef } from "react"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function InvestigationDetailPage() {
  const { id } = useParams()
  const streamUrl = id ? `${API_BASE}/investigations/${id}/stream` : null
  const { steps, answer, error, done } = useSSE(streamUrl)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!done) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [steps, done])

  if (!id) return null

  return (
    <div className="flex flex-col h-full max-w-4xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="mb-8 space-y-4">
        <div className="flex items-center justify-between">
          <Badge variant="outline" className="text-muted-foreground uppercase tracking-wider text-[10px]">
            Investigation ID: {id.toString().slice(0, 8)}...
          </Badge>
          <div className="flex items-center gap-2">
            {!done ? (
              <div className="flex items-center gap-2 text-sm text-primary animate-pulse">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Investigation in progress...</span>
              </div>
            ) : error ? (
              <Badge variant="destructive" className="flex items-center gap-1">
                <AlertCircle className="h-3 w-3" /> Failed
              </Badge>
            ) : (
              <Badge variant="default" className="flex items-center gap-1 bg-emerald-500 hover:bg-emerald-600">
                <CheckCircle2 className="h-3 w-3" /> Completed
              </Badge>
            )}
          </div>
        </div>
        
        {/* Placeholder for query if we had it, but SSE currently doesn't send it. 
            We could fetch detail once if we want the query text. 
            For now, we'll assume the user knows what they searched. */}
      </div>

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
            <div className="rounded-xl border bg-card p-8 shadow-sm ring-1 ring-primary/20">
              <div className="flex items-center gap-2 mb-4 text-primary font-bold">
                <CheckCircle2 className="h-5 w-5" />
                <h3>Final Analysis</h3>
              </div>
              <div className="prose prose-sm prose-invert max-w-none">
                <ReactMarkdown>{answer}</ReactMarkdown>
              </div>
            </div>
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
