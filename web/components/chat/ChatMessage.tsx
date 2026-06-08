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

export function ChatMessageView({
  role,
  content,
  chunkIds,
  confidence,
  isClarification,
  streaming,
}: ChatMessageProps) {
  const isUser = role === "user"
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
            "rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap",
            isUser
              ? "bg-primary text-primary-foreground"
              : isClarification
                ? "bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900 text-foreground"
                : "bg-muted text-foreground",
          )}
        >
          {isClarification && (
            <div className="flex items-center gap-1.5 mb-1 text-amber-700 dark:text-amber-400 text-xs font-medium">
              <AlertTriangle className="size-3.5" />
              Need a bit more info
            </div>
          )}
          {content || (streaming ? <span className="opacity-60">…</span> : "")}
        </div>
        {!isUser && (chunkIds?.length || confidence) && (
          <div className="flex items-center gap-2 flex-wrap text-xs">
            {confidence && (
              <Badge
                variant="outline"
                className={cn(
                  confidence === "low" && "border-amber-300 text-amber-700 dark:text-amber-400",
                  confidence === "medium" && "border-blue-300 text-blue-700 dark:text-blue-400",
                  confidence === "high" && "border-emerald-300 text-emerald-700 dark:text-emerald-400",
                )}
              >
                confidence: {confidence}
              </Badge>
            )}
            {chunkIds?.slice(0, 8).map((c) => (
              <Badge key={c} variant="secondary" className="font-mono text-[10px]">
                {c.slice(0, 8)}
              </Badge>
            ))}
            {chunkIds && chunkIds.length > 8 && (
              <span className="text-muted-foreground">+{chunkIds.length - 8} more</span>
            )}
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
