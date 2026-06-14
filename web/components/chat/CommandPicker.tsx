"use client"

import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { Activity } from "lucide-react"

export type SlashCommand = {
  name: string
  description: string
  icon: React.ReactNode
}

const COMMANDS: SlashCommand[] = [
  { name: "info", description: "Show project overview (services, timeline, clusters)", icon: <Activity className="size-4" /> },
]

interface CommandPickerProps {
  filter: string
  onSelect: (command: string) => void
  onDismiss: () => void
  activeIndex: number
  onActiveIndexChange: (idx: number) => void
}

export function CommandPicker({ filter, onSelect, onDismiss, activeIndex, onActiveIndexChange }: CommandPickerProps) {
  const listRef = useRef<HTMLDivElement>(null)
  const filtered = COMMANDS.filter((c) => c.name.startsWith(filter.toLowerCase()))

  useEffect(() => {
    if (activeIndex >= filtered.length) onActiveIndexChange(0)
  }, [filtered.length, activeIndex, onActiveIndexChange])

  if (filtered.length === 0) return null

  return (
    <div
      ref={listRef}
      className="absolute bottom-full left-0 right-0 mb-2 z-50 rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10 animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2"
    >
      <div className="px-1.5 py-1 text-[10px] font-medium text-muted-foreground tracking-wide uppercase">
        Commands
      </div>
      {filtered.map((cmd, i) => (
        <button
          key={cmd.name}
          type="button"
          className={cn(
            "flex w-full cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none select-none",
            i === activeIndex ? "bg-accent text-accent-foreground" : "text-popover-foreground hover:bg-accent/50",
          )}
          onMouseEnter={() => onActiveIndexChange(i)}
          onMouseDown={(e) => {
            e.preventDefault()
            onSelect(cmd.name)
          }}
        >
          <span className="shrink-0 text-muted-foreground">{cmd.icon}</span>
          <span className="font-mono font-medium">/{cmd.name}</span>
          <span className="ml-1 text-xs text-muted-foreground">{cmd.description}</span>
        </button>
      ))}
    </div>
  )
}

export function getFilteredCommands(filter: string): SlashCommand[] {
  return COMMANDS.filter((c) => c.name.startsWith(filter.toLowerCase()))
}
