"use client"

import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { ChevronDown, ChevronRight, Clock } from "lucide-react"
import { cn } from "@/lib/utils"
import { levelTone } from "@/lib/log-levels"

export type TimelineEntry = {
  service: string | null
  level: string | null
  signature: string
  first_ts: string
  last_ts: string
  repeat_count: number
}

function formatTs(iso: string): string {
  if (!iso) return ""
  return iso.includes("T") ? iso.split("T")[1].slice(0, 8) : iso
}

function formatRange(first: string, last: string): string {
  if (first === last) return formatTs(first)
  return `${formatTs(first)}–${formatTs(last)}`
}

// Optional controlled `open` so a parent (e.g. a quick-action button on the
// assistant turn) can force the panel open. Falls back to uncontrolled
// internal state when omitted.
export function Timeline({
  entries,
  open: openProp,
  onOpenChange,
}: {
  entries: TimelineEntry[]
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const [openUncontrolled, setOpenUncontrolled] = useState(entries.length > 0 && entries.length <= 15)
  const open = openProp ?? openUncontrolled
  const setOpen = (v: boolean) => {
    if (onOpenChange) onOpenChange(v)
    else setOpenUncontrolled(v)
  }

  if (!entries || entries.length === 0) return null

  return (
    <div className="rounded-lg border border-border/60 bg-muted/30 text-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full px-3 py-2 hover:bg-muted/50 transition-colors"
      >
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        <Clock className="size-3.5 text-muted-foreground" />
        <span className="font-medium">Timeline ({entries.length})</span>
        <span className="text-muted-foreground ml-auto">
          chronological view of retrieved events
        </span>
      </button>
      {open && (
        <div className="px-3 py-2 space-y-2">
          {entries.map((e, i) => (
            <div key={i} className="flex items-start gap-3">
              <div className="font-mono text-[10px] text-muted-foreground pt-0.5 w-20 shrink-0 tabular-nums">
                <div title={e.first_ts}>{formatTs(e.first_ts)}</div>
                {e.last_ts !== e.first_ts && (
                  <div className="text-muted-foreground/70" title={e.last_ts}>
                    →{formatTs(e.last_ts)}
                  </div>
                )}
              </div>
              <div className="min-w-0 flex-1 space-y-0.5">
                <div className="flex items-center gap-1.5 flex-wrap">
                  {e.service && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                      {e.service}
                    </Badge>
                  )}
                  {e.level && (
                    <Badge
                      variant="outline"
                      className={cn("text-[10px] px-1.5 py-0", levelTone(e.level))}
                    >
                      {e.level}
                    </Badge>
                  )}
                  {e.repeat_count > 1 && (
                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0 font-mono">
                      ×{e.repeat_count}
                    </Badge>
                  )}
                </div>
                <code
                  className="block text-foreground/90 break-all leading-snug"
                  title={e.signature}
                >
                  {e.signature}
                </code>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
