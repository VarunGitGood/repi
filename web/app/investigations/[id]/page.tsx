"use client"

import { useParams } from "next/navigation"
import { useSSE } from "@/lib/sse"
import { InvestigationStepCard } from "@/components/investigation-step"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { AlertCircle, CheckCircle2, Loader2, Search, ShieldCheck } from "lucide-react"
import ReactMarkdown from "react-markdown"
import { useEffect, useRef, useState } from "react"
import { StructuredAnswerView } from "@/components/structured-answer"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { toast } from "sonner"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function InvestigationDetailPage() {
  const { id } = useParams()
  const streamUrl = id ? `${API_BASE}/investigations/${id}/stream` : null
  const { steps, answer, error, done, clarificationQuestion, awaitingClarification } = useSSE(streamUrl)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [reply, setReply] = useState("")
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!done) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [steps, done, awaitingClarification])

  const handleClarify = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!reply.trim() || submitting) return

    setSubmitting(true)
    try {
      await api.investigations.clarify(id as string, reply)
      setReply("")
      toast.success("Clarification sent. Investigation resuming...")
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setSubmitting(false)
    }
  }

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
            {!done && !awaitingClarification ? (
              <div className="flex items-center gap-2 text-sm text-primary animate-pulse">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Investigation in progress...</span>
              </div>
            ) : awaitingClarification ? (
              <Badge variant="outline" className="flex items-center gap-1 border-amber-500 text-amber-500 animate-pulse">
                <Loader2 className="h-3 w-3 animate-spin" /> Awaiting Clarification
              </Badge>
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
                    {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Resume"}
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
