"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { MessageSquare, Plus } from "lucide-react"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Spinner } from "@/components/ui/spinner"
import type { ConversationSummary } from "@/lib/types"

interface ConversationSidebarProps {
  activeId: string | null
  onSelect: (id: string | null) => void
  refreshKey?: number  // bump to force a re-fetch (e.g. after sending a turn)
  // Conversation ids with a live investigation this session → show a spinner
  // on those rows in place of the message icon. Multiple rows can spin at
  // once since investigations run in parallel across conversations.
  activeInvestigatingIds?: Set<string>
}

export function ConversationSidebar({ activeId, onSelect, refreshKey, activeInvestigatingIds }: ConversationSidebarProps) {
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
    <aside className="w-full md:w-80 border-b md:border-r bg-muted/30 flex flex-col h-auto md:h-full max-h-48 md:max-h-none">
      <div className="p-4 border-b">
        <Button
          variant="outline"
          className="w-full justify-start h-10 px-4 py-2.5 text-sm font-medium"
          onClick={() => onSelect(null)}
        >
          <Plus className="h-4 w-4 mr-2" />
          New conversation
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto py-2">
        {loading && (
          <div className="px-4 py-3 text-xs text-muted-foreground">Loading…</div>
        )}
        {error && (
          <div className="px-4 py-3 text-xs text-destructive">Couldn't load: {error}</div>
        )}
        {!loading && !error && items.length === 0 && (
          <div className="px-4 py-3 text-sm text-muted-foreground">
            No conversations yet. Send your first message →
          </div>
        )}
        {items.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={cn(
              "w-full text-left px-4 py-3 text-sm flex items-start gap-3 hover:bg-muted transition-colors",
              activeId === c.id && "bg-muted font-semibold",
            )}
          >
            {activeInvestigatingIds?.has(c.id) ? (
              <Spinner size="sm" className="mt-0.5 flex-shrink-0 text-primary" />
            ) : (
              <MessageSquare className="size-4 mt-0.5 flex-shrink-0 text-muted-foreground" />
            )}
            <span className="min-w-0 flex-1">
              <span className="line-clamp-2 break-words leading-tight">{c.title || "Untitled"}</span>
              {c.project_name && (
                <span className="block text-xs text-muted-foreground mt-1">
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
