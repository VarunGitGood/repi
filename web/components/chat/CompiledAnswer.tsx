"use client"

import ReactMarkdown from "react-markdown"
import { Badge } from "@/components/ui/badge"
import { AlertTriangle, ArrowDown, Target, Ban, HelpCircle } from "lucide-react"
import type { InvestigationAnswer } from "@/lib/types"

// Strip the model's inline chunk references from prose — same cleanup the old
// plain-text card did.
function stripChunkRefs(s: string): string {
  return s
    .replace(/\s*\[chunk:[^\]]+\]/gi, "")
    .replace(/\s*\[chunk_id:[^\]]+\]/gi, "")
}

// The compiled answer is persisted as `json.dumps(InvestigationAnswer)`. Older
// investigations and clarification messages are plain prose. Try to parse; if
// it isn't the structured object, fall back to rendering text.
function tryParse(answer: string): InvestigationAnswer | null {
  const trimmed = answer.trim()
  if (!trimmed.startsWith("{")) return null
  try {
    const obj = JSON.parse(trimmed)
    if (obj && typeof obj === "object" && ("root_cause" in obj || "affected_services" in obj)) {
      return obj as InvestigationAnswer
    }
  } catch {
    // not JSON — fall through to plain text
  }
  return null
}

const CONFIDENCE_VARIANT: Record<string, "default" | "secondary" | "destructive"> = {
  high: "default",
  medium: "secondary",
  low: "destructive",
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wide">
        {icon}
        {title}
      </div>
      {children}
    </div>
  )
}

export function CompiledAnswer({ answer }: { answer: string }) {
  const parsed = tryParse(answer)

  // Fallback: plain-text answer (clarification text or legacy prose). Rendered
  // as markdown for consistency with the rest of the chat surface.
  if (!parsed) {
    return (
      <div className="md-content rounded-md border bg-muted/40 px-3 py-2 text-sm">
        <ReactMarkdown>{stripChunkRefs(answer)}</ReactMarkdown>
      </div>
    )
  }

  const {
    incident_window,
    affected_services,
    trigger_event,
    propagation_chain,
    root_cause,
    ruled_out_hypotheses,
    assumptions,
    confidence,
    gaps,
  } = parsed

  const conf = (confidence || "").toLowerCase()
  const window = incident_window || {}

  return (
    <div className="rounded-md border bg-muted/40 px-4 py-3 space-y-4 text-sm">
      {/* Header: confidence + incident window */}
      <div className="flex flex-wrap items-center gap-2">
        {conf && (
          <Badge variant={CONFIDENCE_VARIANT[conf] ?? "outline"} className="capitalize">
            {conf} confidence
          </Badge>
        )}
        {(window.start || window.end) && (
          <span className="text-xs text-muted-foreground font-mono">
            {window.start || "?"} → {window.end || "?"}
          </span>
        )}
      </div>

      {/* Root cause — the headline */}
      {root_cause && (
        <Section icon={<Target className="h-3 w-3" />} title="Root cause">
          <div className="md-content text-foreground/90 leading-relaxed">
            <ReactMarkdown>{stripChunkRefs(root_cause)}</ReactMarkdown>
          </div>
        </Section>
      )}

      {/* Affected services */}
      {affected_services && affected_services.length > 0 && (
        <Section icon={<AlertTriangle className="h-3 w-3" />} title="Affected services">
          <div className="flex flex-wrap gap-1.5">
            {affected_services.map((svc) => (
              <Badge key={svc} variant="outline" className="font-mono">
                {svc}
              </Badge>
            ))}
          </div>
        </Section>
      )}

      {/* Trigger event */}
      {trigger_event && (trigger_event.log_line || trigger_event.service) && (
        <Section icon={<AlertTriangle className="h-3 w-3" />} title="Trigger event">
          <div className="rounded border bg-background/60 px-3 py-2 space-y-1">
            <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
              {trigger_event.service && <span className="text-primary">{trigger_event.service}</span>}
              {trigger_event.timestamp && <span>{trigger_event.timestamp}</span>}
            </div>
            {trigger_event.log_line && (
              <pre className="font-mono text-[11px] whitespace-pre-wrap break-all leading-snug text-foreground/85 m-0">
                {trigger_event.log_line}
              </pre>
            )}
          </div>
        </Section>
      )}

      {/* Propagation chain */}
      {propagation_chain && propagation_chain.length > 0 && (
        <Section icon={<ArrowDown className="h-3 w-3" />} title="Propagation">
          <ol className="space-y-1.5">
            {propagation_chain.map((hop, i) => (
              <li key={i} className="flex gap-2 text-xs">
                <span className="text-muted-foreground tabular-nums">{i + 1}.</span>
                <span>
                  <span className="font-mono text-primary">{hop.service}</span>
                  {hop.what ? ` — ${stripChunkRefs(hop.what)}` : ""}
                  {hop.ts ? <span className="text-muted-foreground font-mono"> ({hop.ts})</span> : null}
                </span>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {/* Ruled out */}
      {ruled_out_hypotheses && ruled_out_hypotheses.length > 0 && (
        <Section icon={<Ban className="h-3 w-3" />} title="Ruled out">
          <ul className="space-y-1 text-xs">
            {ruled_out_hypotheses.map((r, i) => (
              <li key={i}>
                <span className="font-medium text-foreground/90">{r.hypothesis}</span>
                {r.why_ruled_out ? <span className="text-muted-foreground"> — {r.why_ruled_out}</span> : null}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* Assumptions + gaps — secondary context, shown last */}
      {assumptions && assumptions.length > 0 && (
        <Section icon={<HelpCircle className="h-3 w-3" />} title="Assumptions">
          <ul className="list-disc pl-4 space-y-0.5 text-xs text-muted-foreground">
            {assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </Section>
      )}
      {gaps && gaps.length > 0 && (
        <Section icon={<HelpCircle className="h-3 w-3" />} title="Gaps">
          <ul className="list-disc pl-4 space-y-0.5 text-xs text-muted-foreground">
            {gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  )
}
