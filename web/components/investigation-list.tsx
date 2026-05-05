"use client"

import { useState, useEffect } from "react"
import { api } from "@/lib/api"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Plus, Clock, Search } from "lucide-react"
import { cn } from "@/lib/utils"

export function InvestigationList() {
  const [investigations, setInvestigations] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const pathname = usePathname()

  useEffect(() => {
    loadInvestigations()
  }, [])

  async function loadInvestigations() {
    try {
      const data = await api.investigations.list()
      setInvestigations(data)
    } catch (err) {
      console.error("Failed to load investigations", err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full border-r bg-muted/20 w-80">
      <div className="p-4 border-b space-y-4">
        <Link href="/investigations" className="flex items-center justify-center w-full">
          <button className="w-full inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 bg-primary text-primary-foreground shadow hover:bg-primary/90 h-9 px-4 py-2">
            <Plus className="mr-2 h-4 w-4" />
            New Investigation
          </button>
        </Link>
        <div className="relative">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            placeholder="Search past investigations..."
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 pl-8 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          />
        </div>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {loading ? (
            <div className="p-4 text-center text-sm text-muted-foreground">Loading...</div>
          ) : investigations.length === 0 ? (
            <div className="p-4 text-center text-sm text-muted-foreground">No history yet.</div>
          ) : (
            investigations.map((inv) => {
              const isActive = pathname === `/investigations/${inv.id}`
              return (
                <Link
                  key={inv.id}
                  href={`/investigations/${inv.id}`}
                  className={cn(
                    "flex flex-col gap-1 rounded-lg p-3 text-sm transition-all hover:bg-muted/50",
                    isActive ? "bg-muted shadow-sm" : ""
                  )}
                >
                  <div className="flex items-start justify-between">
                    <span className="font-semibold line-clamp-1 flex-1 pr-2">
                      {inv.query}
                    </span>
                    <Badge 
                      variant={
                        inv.status === 'completed' ? 'default' : 
                        inv.status === 'failed' ? 'destructive' : 
                        inv.status === 'awaiting_clarification' ? 'outline' : 'secondary'
                      }
                      className={cn(
                        "text-[10px] px-1 h-4 uppercase",
                        inv.status === 'awaiting_clarification' ? "border-amber-500 text-amber-500" : ""
                      )}
                    >
                      {inv.status.replace('_', ' ')}
                    </Badge>
                  </div>
                  <div className="flex items-center text-xs text-muted-foreground">
                    <Clock className="mr-1 h-3 w-3" />
                    {new Date(inv.created_at).toLocaleDateString()} {new Date(inv.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                </Link>
              )
            })
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
