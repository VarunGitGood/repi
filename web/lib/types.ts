// Central type surface for the web app. Single import target
// (`@/lib/types`) for components and tests. Pure type declarations only.

// ── Retrieval / evidence views ────────────────────────────────────────────────

export type Cluster = {
  signature: string
  count: number
  services: string[]
  first_ts: string | null
  last_ts: string | null
}

export type TimelineEntry = {
  service: string | null
  level: string | null
  signature: string
  first_ts: string
  last_ts: string
  repeat_count: number
}

export type CitedChunk = {
  chunk_id: string
  service: string | null
  level: string | null
  timestamp: string | null
  text: string
}

// ── Investigation SSE stream ──────────────────────────────────────────────────

export type StepKind = null | "reflection" | "signal" | "compile"

export interface Step {
  step_number: number
  thought: string
  action?: {
    tool: string
    args: any
  }
  observation?: any
  kind?: StepKind
}

export type InvestigationPhase = "gathering" | "compiling" | "done"

export interface InvestigationStats {
  iterations_used?: number
  reflections_used?: number
  chunks_gathered?: number
  tools_called?: string[]
  compile_source?: string
  compile_attempts?: number
  floor_adjustments?: string[]
  gathering_exit_reason?: string
}

// ── Compiled investigation answer (mirrors repi/investigation/schema.py) ───────
// Everything is optional — the JSON comes off the wire and is rendered
// defensively; a missing section is simply skipped.

export interface TriggerEvent {
  chunk_id?: string
  service?: string
  timestamp?: string
  log_line?: string
}

export interface PropagationHop {
  service?: string
  chunk_id?: string
  ts?: string
  what?: string
}

export interface RuledOut {
  hypothesis?: string
  why_ruled_out?: string
}

export interface InvestigationAnswer {
  incident_window?: { start?: string; end?: string }
  affected_services?: string[]
  trigger_event?: TriggerEvent
  propagation_chain?: PropagationHop[]
  root_cause?: string
  ruled_out_hypotheses?: RuledOut[]
  assumptions?: string[]
  confidence?: string
  gaps?: string[]
}

// ── Chat / conversation ───────────────────────────────────────────────────────

export type ChatMessageProps = {
  role: "user" | "assistant"
  content: string
  chunkIds?: string[]
  confidence?: "low" | "medium" | "high" | null
  isClarification?: boolean
  streaming?: boolean
  clusters?: Cluster[]
  timeline?: TimelineEntry[]
  citedChunks?: CitedChunk[]
  query?: string
  onInvestigateDeeper?: (query: string) => void
}

// Local transcript model. `mode` discriminates chat vs investigate so the page
// can render the right component inline. Investigation turns carry an
// investigationId; `finalAnswer` is populated when the SSE `done` event fires.
export type Turn =
  | ({ mode: "chat" } & ChatMessageProps)
  | {
      mode: "investigate"
      id: string
      investigationId: string
      query: string
      finalAnswer?: string
    }
  | {
      mode: "command"
      command: string
    }

export type ConversationSummary = {
  id: string
  title: string | null
  project_name?: string | null
  created_at: string
  updated_at: string
}
