"use client"

import { useState, useEffect, useMemo } from "react"
import { api } from "@/lib/api"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Plus, Clock, Search } from "lucide-react"
import { Spinner } from "@/components/ui/spinner"
import { cn } from "@/lib/utils"
import { statusBadgeProps } from "@/lib/status"

const ACTIVE_STATUSES = new Set(["started", "running", "awaiting_clarification"])

interface InvestigationRow {
  id: string
  query: string
  status: string
  created_at: string
}

export function InvestigationList() {
  const [investigations, setInvestigations] = useState<InvestigationRow[]>([])
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

  const { active, history } = useMemo(() => {
    const a: InvestigationRow[] = []
    const h: InvestigationRow[] = []
    for (const inv of investigations) {
      if (ACTIVE_STATUSES.has(inv.status)) a.push(inv)
      else h.push(inv)
    }
    return { active: a, history: h }
  }, [investigations])

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
        <div className="p-2 space-y-3">
          {loading ? (
            <div className="p-4 flex justify-center">
              <Spinner size="md" />
            </div>
          ) : investigations.length === 0 ? (
            <div className="p-4 text-center text-sm text-muted-foreground">No history yet.</div>
          ) : (
            <>
              {active.length > 0 && (
                <Section title="Active" count={active.length}>
                  {active.map((inv) => (
                    <InvestigationItem key={inv.id} inv={inv} active pathname={pathname} />
                  ))}
                </Section>
              )}
              {history.length > 0 && (
                <Section title="History" count={history.length}>
                  {history.map((inv) => (
                    <InvestigationItem key={inv.id} inv={inv} pathname={pathname} />
                  ))}
                </Section>
              )}
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="px-2 pt-1 pb-1 flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        <span>{title}</span>
        <span className="text-muted-foreground/60">{count}</span>
      </div>
      {children}
    </div>
  )
}

function InvestigationItem({
  inv,
  active = false,
  pathname,
}: {
  inv: InvestigationRow
  active?: boolean
  pathname: string | null
}) {
  const isActive = pathname === `/investigations/${inv.id}`
  const badge = statusBadgeProps(inv.status)
  return (
    <Link
      href={`/investigations/${inv.id}`}
      className={cn(
        "flex flex-col gap-1 rounded-lg p-3 text-sm transition-all hover:bg-muted/50 relative",
        isActive ? "bg-muted shadow-sm" : ""
      )}
    >
      {active && (
        <span
          aria-hidden
          className="absolute left-1 top-3 h-2 w-2 rounded-full bg-primary animate-pulse"
        />
      )}
      <div className={cn("flex items-start justify-between", active && "pl-3")}>
        <span className="font-semibold line-clamp-1 flex-1 pr-2">
          {inv.query}
        </span>
        <Badge
          variant={badge.variant}
          className={cn("text-[10px] px-1 h-4 uppercase", badge.className)}
        >
          {badge.label}
        </Badge>
      </div>
      <div className={cn("flex items-center text-xs text-muted-foreground", active && "pl-3")}>
        <Clock className="mr-1 h-3 w-3" />
        {new Date(inv.created_at).toLocaleDateString()} {new Date(inv.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
      </div>
    </Link>
  )
}
