"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { FolderOpen, Plus } from "lucide-react"
import { toast } from "sonner"

export type ProjectSummary = {
  id: string
  name: string
  settings: Record<string, any>
  service_count: number
}

interface ProjectPickerProps {
  onSelect: (project: ProjectSummary) => void
}

/**
 * New-chat step 1: pick the project to scope the conversation to.
 * - 0 projects → inline create form
 * - exactly 1 → auto-select, no picker shown
 * - 2+ → cards
 */
export function ProjectPicker({ onSelect }: ProjectPickerProps) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null)
  const [newName, setNewName] = useState("")
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    let cancelled = false
    api.projects.list()
      .then((rows: ProjectSummary[]) => {
        if (cancelled) return
        if (rows.length === 1) onSelect(rows[0])
        else setProjects(rows)
      })
      .catch((e: any) => {
        if (!cancelled) toast.error("Could not load projects: " + e.message)
        setProjects([])
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function createProject() {
    const name = newName.trim()
    if (!name) return
    setCreating(true)
    try {
      const p = await api.projects.create(name)
      onSelect(p)
    } catch (e: any) {
      toast.error("Could not create project: " + e.message)
    } finally {
      setCreating(false)
    }
  }

  if (projects === null) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <Spinner size="lg" label="Loading projects…" />
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col items-center justify-center px-4">
      <div className="size-12 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
        <FolderOpen className="size-6 text-primary" />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight mb-1">Select a project</h1>
      <p className="text-muted-foreground text-sm max-w-md text-center mb-6">
        Conversations, timelines and investigations are scoped to one project.
      </p>

      {projects.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 w-full max-w-lg mb-6">
          {projects.map((p) => (
            <button
              key={p.id}
              type="button"
              data-project-card={p.name}
              onClick={() => onSelect(p)}
              className="rounded-xl border bg-card/50 hover:bg-muted/50 transition-colors px-4 py-3 text-left"
            >
              <div className="font-medium text-sm">{p.name}</div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {p.service_count} service{p.service_count === 1 ? "" : "s"}
              </div>
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 w-full max-w-sm">
        <Input
          placeholder="New project name…"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") createProject() }}
        />
        <Button size="sm" onClick={createProject} disabled={creating || !newName.trim()}>
          <Plus className="h-3.5 w-3.5 mr-1.5" />
          Create
        </Button>
      </div>
    </div>
  )
}
