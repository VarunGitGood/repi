"use client"

import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { ChevronDown, ChevronRight, Layers } from "lucide-react"
import { cn } from "@/lib/utils"

export type Cluster = {
  signature: string
  count: number
  services: string[]
  first_ts: string | null
  last_ts: string | null
}

function formatRange(first: string | null, last: string | null): string {
  if (!first && !last) return ""
  if (first === last || !last) return formatTs(first)
  if (!first) return formatTs(last)
  return `${formatTs(first)}–${formatTs(last)}`
}

function formatTs(iso: string | null): string {
  if (!iso) return ""
  // Show HH:MM:SS for tight inline display. Full timestamp on hover via title.
  const t = iso.includes("T") ? iso.split("T")[1].slice(0, 8) : iso
  return t
}

export function EventClusters({ clusters }: { clusters: Cluster[] }) {
  // Default open when small enough to scan at a glance.
  const [open, setOpen] = useState(clusters.length > 0 && clusters.length <= 5)

  if (!clusters || clusters.length === 0) return null

  return (
    <div className="rounded-lg border border-border/60 bg-muted/30 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 w-full px-3 py-2 hover:bg-muted/50 transition-colors"
      >
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        <Layers className="size-3.5 text-muted-foreground" />
        <span className="font-medium">Event clusters ({clusters.length})</span>
        <span className="text-muted-foreground ml-auto">
          across {clusters.length} signature{clusters.length === 1 ? "" : "s"} in retrieved chunks
        </span>
      </button>
      {open && (
        <div className="divide-y divide-border/40">
          {clusters.map((c, i) => (
            <div key={i} className="px-3 py-2 space-y-1">
              <div className="flex items-start gap-2">
                <Badge variant="secondary" className="font-mono shrink-0">
                  {c.count}×
                </Badge>
                <code
                  className="text-foreground/90 break-all"
                  title={c.signature}
                >
                  {c.signature}
                </code>
              </div>
              <div className="flex items-center gap-1.5 flex-wrap pl-1 text-[10px] text-muted-foreground">
                {c.services.map((s) => (
                  <Badge key={s} variant="outline" className="text-[10px] px-1.5 py-0">
                    {s}
                  </Badge>
                ))}
                {(c.first_ts || c.last_ts) && (
                  <span
                    className={cn("ml-1 font-mono")}
                    title={`${c.first_ts ?? ""} → ${c.last_ts ?? ""}`}
                  >
                    {formatRange(c.first_ts, c.last_ts)}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
