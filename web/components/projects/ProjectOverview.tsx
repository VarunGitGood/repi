"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { EventClusters, type Cluster } from "@/components/chat/EventClusters"
import { cn } from "@/lib/utils"
import { levelTone } from "@/lib/log-levels"
import { Activity, Microscope, MessageSquare, Server } from "lucide-react"
import { toast } from "sonner"

export type OverviewEvent = {
  kind: string
  ts: string
  service: string | null
  signature: string | null
  level: string | null
  title: string
  count: number
}

export type SuggestedAction = {
  kind: "investigate" | "chat"
  label: string
  query: string
}

type Overview = {
  window: string
  time_from: string
  time_to: string
  anchored_to_latest: boolean
  events: OverviewEvent[]
  clusters: Cluster[]
  services: { name: string; chunk_count: number; last_seen: string | null }[]
  suggested_actions: SuggestedAction[]
}

function shortTs(iso: string): string {
  if (!iso) return ""
  return iso.includes("T") ? iso.split("T")[1].slice(0, 8) : iso
}

function shortDate(iso: string): string {
  return iso?.split("T")[0] ?? ""
}

const KIND_LABEL: Record<string, string> = {
  begins: "begins",
  spike: "spike",
  subsides: "subsides",
  new_pattern: "new pattern",
  health_degraded: "degraded",
  health_recovered: "recovered",
}

interface ProjectOverviewProps {
  projectId: string
  projectName: string
  onAction: (action: SuggestedAction) => void
}

/**
 * The landing panel of a new project conversation: heuristic event timeline
 * ("what happened recently?"), top error clusters ("what is breaking?"),
 * services, and suggested next actions. Fetched live on mount; not persisted
 * as a chat message.
 */
export function ProjectOverview({ projectId, projectName, onAction }: ProjectOverviewProps) {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    setOverview(null)
    api.projects.overview(projectId)
      .then((d: Overview) => { if (!cancelled) setOverview(d) })
      .catch((e: any) => {
        if (!cancelled) {
          setFailed(true)
          toast.error("Could not load project overview: " + e.message)
        }
      })
    return () => { cancelled = true }
  }, [projectId])

  if (failed) return null
  if (!overview) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8 flex justify-center text-muted-foreground">
        <Spinner size="sm" label={`Loading ${projectName} timeline…`} />
      </div>
    )
  }

  const hasData = overview.events.length > 0 || overview.clusters.length > 0
  // Show the date alongside times when the window isn't "today".
  const spansDays = shortDate(overview.time_from) !== shortDate(overview.time_to)

  return (
    <div className="max-w-3xl mx-auto px-4 space-y-3">
      <div className="flex items-center gap-2 text-sm">
        <Activity className="size-4 text-primary" />
        <span className="font-medium">{projectName}</span>
        <Badge variant="outline" className="text-[10px]">last {overview.window}</Badge>
        {overview.anchored_to_latest && (
          <span className="text-xs text-muted-foreground">
            showing latest data ({shortDate(overview.time_to)})
          </span>
        )}
      </div>

      {!hasData ? (
        <div className="rounded-lg border border-border/60 bg-muted/30 px-4 py-6 text-sm text-muted-foreground text-center">
          No log data in this project yet. Ingest a file or register a watcher,
          then this timeline fills in.
        </div>
      ) : (
        <>
          {overview.events.length > 0 && (
            <div className="rounded-lg border border-border/60 bg-muted/30 text-xs">
              <div className="px-3 py-2 font-medium border-b border-border/40">
                Timeline
                <span className="text-muted-foreground font-normal ml-2">
                  what happened recently
                </span>
              </div>
              <div className="px-3 py-2 space-y-1.5">
                {overview.events.map((e, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <div className="font-mono text-[10px] text-muted-foreground pt-0.5 w-20 shrink-0 tabular-nums" title={e.ts}>
                      <div>{shortTs(e.ts)}</div>
                      {spansDays && <div className="text-muted-foreground/70">{shortDate(e.ts)}</div>}
                    </div>
                    <div className="min-w-0 flex-1 flex items-start gap-1.5 flex-wrap">
                      <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", levelTone(e.level))}>
                        {KIND_LABEL[e.kind] ?? e.kind}
                      </Badge>
                      {e.service && (
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                          {e.service}
                        </Badge>
                      )}
                      <span className="text-foreground/90 break-all leading-snug">{e.title}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {overview.clusters.length > 0 && (
            <EventClusters clusters={overview.clusters} />
          )}
        </>
      )}

      {overview.services.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap text-xs">
          <Server className="size-3.5 text-muted-foreground" />
          {overview.services.map((s) => (
            <Badge key={s.name} variant="secondary" className="text-[10px]" title={`${s.chunk_count} chunks`}>
              {s.name}
            </Badge>
          ))}
        </div>
      )}

      {hasData && overview.suggested_actions.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {overview.suggested_actions.map((a, i) => (
            <Button
              key={i}
              size="sm"
              variant="outline"
              className="h-7 px-2.5 text-xs"
              onClick={() => onAction(a)}
            >
              {a.kind === "investigate"
                ? <Microscope className="size-3 mr-1" />
                : <MessageSquare className="size-3 mr-1" />}
              {a.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  )
}
