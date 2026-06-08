"use client"

import { Step } from "@/lib/sse"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Spinner } from "@/components/ui/spinner"
import { Terminal, Brain, Search, ChevronDown, ChevronRight, Sparkles, Lightbulb, Flag } from "lucide-react"
import { useState } from "react"
import ReactMarkdown from "react-markdown"
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter"
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism"

export function InvestigationStepCard({ step }: { step: Step }) {
  const [showTool, setShowTool] = useState(false)
  const [showObservation, setShowObservation] = useState(false)

  // Reflection turn — internal re-plan, not user-facing content. Render as a
  // small spinner row so the user knows the loop is thinking, without dumping
  // the full re-plan text into the transcript.
  if (step.kind === "reflection") {
    return (
      <div className="relative pl-8 pb-4 last:pb-0">
        <div className="absolute left-0 top-1 h-6 w-6 rounded-full border-2 border-border bg-background flex items-center justify-center z-10">
          <Spinner size="sm" />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground italic mt-1">
          reflecting…
        </div>
      </div>
    )
  }

  // Compile phase — also internal. Single neutral line.
  if (step.kind === "compile") {
    return (
      <div className="relative pl-8 pb-4 last:pb-0">
        <div className="absolute left-0 top-1 h-6 w-6 rounded-full border-2 border-primary bg-background flex items-center justify-center z-10">
          <Sparkles className="h-3 w-3 text-primary" />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground italic mt-1">
          compiling answer…
        </div>
      </div>
    )
  }

  if (step.kind === "signal") {
    return (
      <div className="relative pl-8 pb-4 last:pb-0">
        <div className="absolute left-0 top-1 h-6 w-6 rounded-full border-2 border-primary bg-background flex items-center justify-center z-10">
          <Flag className="h-3 w-3 text-primary" />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono mt-1">
          done_gathering
          {step.action?.args?.reason ? ` — ${step.action.args.reason}` : ""}
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

      <div className="space-y-3">
        {/* Thought */}
        <div className="flex items-start gap-3">
          <Brain className="h-5 w-5 mt-0.5 text-primary" />
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
                <Terminal className="h-3 w-3 text-muted-foreground" />
                <span className="text-primary font-medium">tool:</span>
                <span>{step.action.tool}</span>
              </div>
              {showTool ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            </button>
            {showTool && (
              <div className="p-3 bg-muted/20">
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
          <div className="ml-8 border rounded-md overflow-hidden bg-card/50">
            <button
              onClick={() => setShowObservation(!showObservation)}
              className="w-full flex items-center justify-between p-2 px-3 text-xs font-mono bg-muted/50 hover:bg-muted transition-colors"
            >
              <div className="flex items-center gap-2">
                <Search className="h-3 w-3 text-muted-foreground" />
                <span className="text-primary font-medium">observation:</span>
                <span className="text-muted-foreground italic">
                  {step.action?.tool === "ask_user" && step.observation?.result?.reply
                    ? `Reply: ${step.observation.result.reply}`
                    : Array.isArray(step.observation) ? `${step.observation.length} items` : 'Result received'}
                </span>
              </div>
              {showObservation ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            </button>
            {showObservation && (
              <div className="max-h-[300px] overflow-auto p-3 bg-muted/20">
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
