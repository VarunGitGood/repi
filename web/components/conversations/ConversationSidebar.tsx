"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { MessageSquare, Plus } from "lucide-react"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

type ConversationSummary = {
  id: string
  title: string | null
  project_name?: string | null
  created_at: string
  updated_at: string
}

interface ConversationSidebarProps {
  activeId: string | null
  onSelect: (id: string | null) => void
  refreshKey?: number  // bump to force a re-fetch (e.g. after sending a turn)
}

export function ConversationSidebar({ activeId, onSelect, refreshKey }: ConversationSidebarProps) {
  const [items, setItems] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.conversations.list()
      .then((rows) => { if (!cancelled) { setItems(rows); setLoading(false) } })
      .catch((e) => { if (!cancelled) { setError(e.message); setLoading(false) } })
    return () => { cancelled = true }
  }, [refreshKey])

  return (
    <aside className="w-64 border-r bg-muted/30 flex flex-col h-full">
      <div className="p-3 border-b">
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start"
          onClick={() => onSelect(null)}
        >
          <Plus className="h-3.5 w-3.5 mr-2" />
          New conversation
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto py-1">
        {loading && (
          <div className="px-3 py-2 text-xs text-muted-foreground">Loading…</div>
        )}
        {error && (
          <div className="px-3 py-2 text-xs text-destructive">Couldn't load: {error}</div>
        )}
        {!loading && !error && items.length === 0 && (
          <div className="px-3 py-2 text-xs text-muted-foreground">
            No conversations yet. Send your first message →
          </div>
        )}
        {items.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={cn(
              "w-full text-left px-3 py-2 text-xs flex items-start gap-2 hover:bg-muted transition-colors",
              activeId === c.id && "bg-muted font-medium",
            )}
          >
            <MessageSquare className="size-3.5 mt-0.5 flex-shrink-0 text-muted-foreground" />
            <span className="min-w-0">
              <span className="line-clamp-2 break-words">{c.title || "Untitled"}</span>
              {c.project_name && (
                <span className="block text-[10px] text-muted-foreground mt-0.5">
                  {c.project_name}
                </span>
              )}
            </span>
          </button>
        ))}
      </div>
    </aside>
  )
}
