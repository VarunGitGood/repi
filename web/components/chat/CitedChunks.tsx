"use client"

import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { ChevronDown, ChevronRight, FileText } from "lucide-react"

export type CitedChunk = {
  chunk_id: string
  service: string | null
  level: string | null
  timestamp: string | null
  text: string
}

function shortTs(iso: string | null): string {
  if (!iso) return ""
  return iso.includes("T") ? iso.split("T")[1].slice(0, 8) : iso
}

export function CitedChunks({
  chunks,
  open: openProp,
  onOpenChange,
}: {
  chunks: CitedChunk[]
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  // Default closed — raw chunks are the debug view; users seeking them
  // know to click. Timeline and clusters carry the story.
  const [openUncontrolled, setOpenUncontrolled] = useState(false)
  const open = openProp ?? openUncontrolled
  const setOpen = (v: boolean) => {
    if (onOpenChange) onOpenChange(v)
    else setOpenUncontrolled(v)
  }

  if (!chunks || chunks.length === 0) return null

  return (
    <div className="rounded-lg border border-border/60 bg-muted/30 text-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full px-3 py-2 hover:bg-muted/50 transition-colors"
      >
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        <FileText className="size-3.5 text-muted-foreground" />
        <span className="font-medium">Cited chunks ({chunks.length})</span>
        <span className="text-muted-foreground ml-auto">
          raw log lines the answer was grounded on
        </span>
      </button>
      {open && (
        <div className="px-3 py-2 space-y-2 max-h-[40vh] overflow-y-auto">
          {chunks.map((c) => (
            <div key={c.chunk_id} className="rounded-md border border-border/40 bg-background/50 px-3 py-2 space-y-1">
              <div className="flex items-center gap-1.5 flex-wrap text-[10px]">
                {c.service && (
                  <Badge variant="outline" className="px-1.5 py-0">
                    {c.service}
                  </Badge>
                )}
                {c.level && (
                  <Badge variant="outline" className="px-1.5 py-0">
                    {c.level}
                  </Badge>
                )}
                {c.timestamp && (
                  <span className="font-mono text-muted-foreground" title={c.timestamp}>
                    {shortTs(c.timestamp)}
                  </span>
                )}
              </div>
              <pre className="font-mono text-[11px] whitespace-pre-wrap break-all leading-snug text-foreground/85">
                {c.text}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
