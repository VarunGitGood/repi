"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { AlertCircle, Clock, Database, Layers, ShieldCheck, Zap } from "lucide-react"
import { Separator } from "@/components/ui/separator"

interface StructuredAnswer {
  root_cause: string
  incident_window: { start: string; end: string }
  affected_services: string[]
  trigger_event: {
    service: string
    timestamp: string
    log_line: string
    chunk_id: string
  }
  propagation_chain: Array<{
    ts: string
    service: string
    what: string
    chunk_id: string
  }>
  ruled_out_hypotheses: Array<{
    hypothesis: string
    why_ruled_out: string
  }>
  assumptions: string[]
  confidence: "low" | "medium" | "high"
  gaps: string[]
}

export function StructuredAnswerView({ data }: { data: string }) {
  let parsed: StructuredAnswer | null = null
  try {
    parsed = JSON.parse(data)
  } catch (e) {
    // If not JSON, it might just be a string answer
    return (
      <div className="prose prose-sm prose-invert max-w-none">
        {data}
      </div>
    )
  }

  if (!parsed || !parsed.root_cause) {
    return <div className="prose prose-sm prose-invert max-w-none">{data}</div>
  }

  return (
    <div className="space-y-6">
      {/* Root Cause Hero */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Badge variant={parsed.confidence === "high" ? "default" : "outline"} 
                 className={parsed.confidence === "high" ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/50" : ""}>
            {parsed.confidence.toUpperCase()} CONFIDENCE
          </Badge>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            <span>{new Date(parsed.incident_window.start).toLocaleString()} - {new Date(parsed.incident_window.end).toLocaleTimeString()}</span>
          </div>
        </div>
        <h2 className="text-xl font-bold text-primary leading-tight">
          {parsed.root_cause}
        </h2>
      </div>

      <Separator className="opacity-20" />

      {/* Trigger Event */}
      <div className="bg-primary/5 rounded-lg border border-primary/20 p-4 space-y-3">
        <div className="flex items-center gap-2 text-primary font-semibold text-sm">
          <Zap className="h-4 w-4" />
          Trigger Event
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="font-mono text-[10px]">{parsed.trigger_event.service}</Badge>
            <span className="text-[10px] text-muted-foreground">{new Date(parsed.trigger_event.timestamp).toLocaleString()}</span>
          </div>
          <code className="block text-xs bg-black/40 p-2 rounded border border-white/5 font-mono text-emerald-300/90 break-words">
            {parsed.trigger_event.log_line}
          </code>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Propagation Chain */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Layers className="h-4 w-4 text-blue-400" />
            Propagation Chain
          </div>
          <div className="space-y-3 pl-2 border-l border-blue-400/20 ml-2">
            {parsed.propagation_chain.map((step, i) => (
              <div key={i} className="relative pl-4 space-y-1">
                <div className="absolute left-[-9px] top-1.5 h-4 w-4 rounded-full bg-background border-2 border-blue-400 flex items-center justify-center">
                  <div className="h-1.5 w-1.5 rounded-full bg-blue-400" />
                </div>
                <div className="text-xs font-bold text-blue-300">{step.service}</div>
                <p className="text-xs text-muted-foreground">{step.what}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Impacted Services */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Database className="h-4 w-4 text-amber-400" />
            Impacted Services
          </div>
          <div className="flex flex-wrap gap-2">
            {parsed.affected_services.map(svc => (
              <Badge key={svc} variant="outline" className="bg-amber-400/5 text-amber-400 border-amber-400/30">
                {svc}
              </Badge>
            ))}
          </div>
          
          <Separator className="opacity-10" />

          {/* Ruled Out */}
          <div className="space-y-3">
             <div className="flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
              Hypotheses Ruled Out
            </div>
            {parsed.ruled_out_hypotheses.map((h, i) => (
              <div key={i} className="text-xs space-y-1 bg-emerald-500/5 p-2 rounded border border-emerald-500/10">
                <span className="font-bold text-emerald-400">{h.hypothesis}</span>
                <p className="text-muted-foreground italic">{h.why_ruled_out}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Assumptions & Gaps */}
      {(parsed.assumptions.length > 0 || parsed.gaps.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4 border-t border-white/5">
          {parsed.assumptions.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Assumptions</h4>
              <ul className="list-disc list-inside text-xs text-muted-foreground space-y-1">
                {parsed.assumptions.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
          {parsed.gaps.length > 0 && (
            <div className="space-y-2">
               <h4 className="text-xs font-bold uppercase tracking-wider text-red-400/80">Information Gaps</h4>
               <ul className="list-disc list-inside text-xs text-red-400/60 space-y-1">
                {parsed.gaps.map((g, i) => <li key={i}>{g}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
