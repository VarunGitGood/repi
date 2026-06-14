"use client"

import { useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { AlertTriangle, Clock, Layers, Microscope, Sparkles, User } from "lucide-react"
import { EventClusters } from "@/components/chat/EventClusters"
import { Timeline } from "@/components/chat/Timeline"
import { CitedChunks } from "@/components/chat/CitedChunks"
import type { ChatMessageProps } from "@/lib/types"

export type { ChatMessageProps }

function cleanContent(raw: string): string {
  if (!raw) return raw
  return raw
    .replace(/\s*\[chunk:[^\]]+\]/gi, "")
    .replace(/\s*\[chunk_id:[^\]]+\]/gi, "")
    .replace(/[ \t]+([.,;:])/g, "$1")
}

export function ChatMessageView({
  role,
  content,
  chunkIds: _chunkIds,
  confidence,
  isClarification,
  streaming,
  clusters,
  timeline,
  citedChunks,
  query,
  onInvestigateDeeper,
}: ChatMessageProps) {
  const isUser = role === "user"
  const displayed = isUser ? content : cleanContent(content)

  // Lift open state out of the three panels so the quick-action buttons can
  // open them on demand. Uncontrolled fallback inside each panel handles
  // the no-button path.
  const [timelineOpen, setTimelineOpen] = useState<boolean | undefined>(undefined)
  const [clustersOpen, setClustersOpen] = useState<boolean | undefined>(undefined)
  const [chunksOpen, setChunksOpen] = useState<boolean | undefined>(undefined)

  const timelineRef = useRef<HTMLDivElement>(null)
  const clustersRef = useRef<HTMLDivElement>(null)
  const chunksRef = useRef<HTMLDivElement>(null)

  const showAndScroll = (
    setter: (v: boolean) => void,
    ref: React.RefObject<HTMLDivElement | null>,
  ) => {
    setter(true)
    // Defer the scroll so the panel has rendered open before measuring.
    requestAnimationFrame(() => {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })
    })
  }

  const hasTimeline = !!(timeline && timeline.length > 0)
  const hasClusters = !!(clusters && clusters.length > 0)
  const hasChunks = !!(citedChunks && citedChunks.length > 0)
  const showQuickActions =
    !isUser && !streaming && (hasTimeline || hasClusters || (onInvestigateDeeper && query))

  return (
    <div className={cn("flex gap-3 max-w-3xl mx-auto px-4", isUser ? "justify-end" : "justify-start")}>
      {!isUser && (
        <div className="flex-shrink-0 size-8 rounded-full bg-primary/10 flex items-center justify-center mt-1">
          <Sparkles className="size-4 text-primary" />
        </div>
      )}
      <div className={cn("max-w-[85%] space-y-2", isUser && "items-end")}>
        <div
          className={cn(
            "rounded-2xl px-4 py-2.5 text-sm border",
            isUser
              ? "bg-primary text-primary-foreground border-transparent whitespace-pre-wrap"
              : "bg-muted text-foreground border-transparent",
          )}
        >
          {isClarification && (
            <div className="flex items-center gap-1.5 mb-1 text-muted-foreground text-xs font-medium">
              <AlertTriangle className="size-3.5" />
              Need a bit more info
            </div>
          )}
          {isUser ? (
            displayed
          ) : displayed ? (
            // Assistant prose is markdown — render it. The `md-content` class
            // carries the typographic spacing + Notion-style orange backticks.
            <div className="md-content">
              <ReactMarkdown>{displayed}</ReactMarkdown>
            </div>
          ) : streaming ? (
            <span className="opacity-60">…</span>
          ) : (
            ""
          )}
        </div>

        {!isUser && confidence && (
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <Badge variant="outline" className="text-muted-foreground">
              confidence: {confidence}
            </Badge>
          </div>
        )}

        {showQuickActions && (
          <div className="flex items-center gap-1.5 flex-wrap text-xs">
            {hasTimeline && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs"
                onClick={() => showAndScroll(setTimelineOpen, timelineRef)}
              >
                <Clock className="size-3" />
                Show timeline
              </Button>
            )}
            {hasClusters && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs"
                onClick={() => showAndScroll(setClustersOpen, clustersRef)}
              >
                <Layers className="size-3" />
                Show clusters
              </Button>
            )}
            {onInvestigateDeeper && query && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs"
                onClick={() => onInvestigateDeeper(query)}
              >
                <Microscope className="size-3" />
                Investigate deeper
              </Button>
            )}
          </div>
        )}

        {hasTimeline && (
          <div ref={timelineRef}>
            <Timeline entries={timeline!} open={timelineOpen} onOpenChange={setTimelineOpen} />
          </div>
        )}
        {hasClusters && (
          <div ref={clustersRef}>
            <EventClusters clusters={clusters!} open={clustersOpen} onOpenChange={setClustersOpen} />
          </div>
        )}
        {hasChunks && (
          <div ref={chunksRef}>
            <CitedChunks chunks={citedChunks!} open={chunksOpen} onOpenChange={setChunksOpen} />
          </div>
        )}
      </div>
      {isUser && (
        <div className="flex-shrink-0 size-8 rounded-full bg-muted flex items-center justify-center mt-1">
          <User className="size-4 text-muted-foreground" />
        </div>
      )}
    </div>
  )
}
