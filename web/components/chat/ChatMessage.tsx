"use client"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { AlertTriangle, Sparkles, User } from "lucide-react"

export type ChatMessageProps = {
  role: "user" | "assistant"
  content: string
  chunkIds?: string[]
  confidence?: "low" | "medium" | "high" | null
  isClarification?: boolean
  streaming?: boolean
}

// Strip raw chunk citations the LLM may still inline despite the system
// prompt asking it not to. Catches [chunk:abc...] and bare hex/uuid runs in
// brackets so the user sees clean prose.
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
}: ChatMessageProps) {
  const isUser = role === "user"
  const displayed = isUser ? content : cleanContent(content)
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
            "rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap border",
            isUser
              ? "bg-primary text-primary-foreground border-transparent"
              : "bg-muted text-foreground border-transparent",
          )}
        >
          {isClarification && (
            <div className="flex items-center gap-1.5 mb-1 text-muted-foreground text-xs font-medium">
              <AlertTriangle className="size-3.5" />
              Need a bit more info
            </div>
          )}
          {displayed || (streaming ? <span className="opacity-60">…</span> : "")}
        </div>
        {!isUser && confidence && (
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <Badge variant="outline" className="text-muted-foreground">
              confidence: {confidence}
            </Badge>
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
