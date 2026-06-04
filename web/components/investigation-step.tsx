"use client"

import { Step } from "@/lib/sse"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Terminal, Brain, Search, ChevronDown, ChevronRight, Sparkles, Lightbulb, Flag } from "lucide-react"
import { useState } from "react"
import ReactMarkdown from "react-markdown"
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter"
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism"

export function InvestigationStepCard({ step }: { step: Step }) {
  const [showTool, setShowTool] = useState(false)
  const [showObservation, setShowObservation] = useState(false)

  // Special-kind steps render with their own visual treatment.
  if (step.kind === "compile") {
    return (
      <div className="relative pl-8 pb-8 last:pb-0">
        <div className="absolute left-0 top-1 h-6 w-6 rounded-full border-2 border-violet-500 bg-violet-500/10 flex items-center justify-center z-10">
          <Sparkles className="h-3 w-3 text-violet-400" />
        </div>
        <div className="flex items-start gap-3">
          <div className="flex-1 text-sm leading-relaxed text-violet-200/90 bg-violet-500/5 p-3 rounded-lg border border-violet-500/20">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-violet-300 mb-2">
              <Sparkles className="h-3 w-3" /> Compile phase
            </div>
            <ReactMarkdown>{step.thought}</ReactMarkdown>
          </div>
        </div>
      </div>
    )
  }

  if (step.kind === "reflection") {
    return (
      <div className="relative pl-8 pb-8 last:pb-0">
        <div className="absolute left-0 top-1 h-6 w-6 rounded-full border-2 border-amber-500 bg-amber-500/10 flex items-center justify-center z-10">
          <Lightbulb className="h-3 w-3 text-amber-400" />
        </div>
        <div className="flex items-start gap-3">
          <div className="flex-1 text-sm leading-relaxed text-amber-100/90 bg-amber-500/5 p-3 rounded-lg border border-amber-500/20">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-amber-300 mb-2">
              <Lightbulb className="h-3 w-3" /> Reflection
            </div>
            <ReactMarkdown>{step.thought}</ReactMarkdown>
          </div>
        </div>
      </div>
    )
  }

  if (step.kind === "signal") {
    return (
      <div className="relative pl-8 pb-8 last:pb-0">
        <div className="absolute left-0 top-1 h-6 w-6 rounded-full border-2 border-sky-500 bg-sky-500/10 flex items-center justify-center z-10">
          <Flag className="h-3 w-3 text-sky-400" />
        </div>
        <div className="flex items-center gap-3 text-sm text-sky-300">
          <Flag className="h-4 w-4" />
          <span className="font-mono">
            done_gathering
            {step.action?.args?.reason ? ` — ${step.action.args.reason}` : ""}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="relative pl-8 pb-8 last:pb-0">
      {/* Timeline connector */}
      <div className="absolute left-[11px] top-2 bottom-0 w-[2px] bg-border group-last:hidden" />

      {/* Step circle */}
      <div className="absolute left-0 top-1 h-6 w-6 rounded-full border-2 border-primary bg-background flex items-center justify-center z-10">
        <span className="text-[10px] font-bold">{step.step_number}</span>
      </div>

      <div className="space-y-4">
        {/* Thought */}
        <div className="flex items-start gap-3">
          {step.action?.tool === "ask_user" ? (
            <Brain className="h-5 w-5 mt-0.5 text-amber-400" />
          ) : (
            <Brain className="h-5 w-5 mt-0.5 text-blue-400" />
          )}
          <div className="flex-1 text-sm leading-relaxed text-foreground/90 bg-muted/30 p-3 rounded-lg border border-border/50">
            <ReactMarkdown>{step.thought}</ReactMarkdown>
          </div>
        </div>

        {/* Action/Tool Call */}
        {step.action && (
          <div className="ml-8 border rounded-md overflow-hidden bg-card/50">
            <button 
              onClick={() => setShowTool(!showTool)}
              className="w-full flex items-center justify-between p-2 px-3 text-xs font-mono bg-muted/50 hover:bg-muted transition-colors"
            >
              <div className="flex items-center gap-2">
                <Terminal className="h-3 w-3" />
                <span className="text-primary font-bold">tool:</span>
                <span>{step.action.tool}</span>
              </div>
              {showTool ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            </button>
            {showTool && (
              <div className="p-3 bg-black/20">
                <SyntaxHighlighter 
                  language="json" 
                  style={vscDarkPlus}
                  customStyle={{ margin: 0, padding: 0, background: 'transparent', fontSize: '11px' }}
                >
                  {JSON.stringify(step.action.args, null, 2)}
                </SyntaxHighlighter>
              </div>
            )}
          </div>
        )}

        {/* Observation */}
        {step.observation && (
          <div className="ml-8 border rounded-md overflow-hidden bg-card/50 border-emerald-500/20">
            <button 
              onClick={() => setShowObservation(!showObservation)}
              className="w-full flex items-center justify-between p-2 px-3 text-xs font-mono bg-emerald-500/10 hover:bg-emerald-500/20 transition-colors"
            >
              <div className="flex items-center gap-2 text-emerald-400">
                <Search className="h-3 w-3" />
                <span className="font-bold">observation:</span>
                <span className="text-muted-foreground italic">
                  {step.action?.tool === "ask_user" && step.observation?.result?.reply 
                    ? `Reply: ${step.observation.result.reply}`
                    : Array.isArray(step.observation) ? `${step.observation.length} items` : 'Result received'}
                </span>
              </div>
              {showObservation ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            </button>
            {showObservation && (
              <div className="max-h-[300px] overflow-auto p-3 bg-black/20">
                <SyntaxHighlighter 
                  language="json" 
                  style={vscDarkPlus}
                  customStyle={{ margin: 0, padding: 0, background: 'transparent', fontSize: '11px' }}
                >
                  {JSON.stringify(step.observation, null, 2)}
                </SyntaxHighlighter>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
