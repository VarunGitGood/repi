"use client"

import { useState, useEffect } from "react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { toast } from "sonner"
import { Plus, Trash2 } from "lucide-react"
import { Spinner } from "@/components/ui/spinner"

export function WatcherForm() {
  const [watchers, setWatchers] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [newWatcher, setNewWatcher] = useState({ service_name: "", watch_path: "", env: "production" })
  const [isDemo, setIsDemo] = useState(false)

  useEffect(() => {
    const demo = typeof window !== "undefined" && (
      localStorage.getItem("repi.demoMode") === "1" ||
      new URLSearchParams(window.location.search).get("demo") === "1" ||
      process.env.NEXT_PUBLIC_DEMO_MODE === "true"
    )
    setIsDemo(!!demo)
    loadWatchers()
  }, [])

  async function loadWatchers() {
    try {
      const data = await api.watchers.list()
      setWatchers(data)
    } catch (err: any) {
      toast.error("Failed to load watchers")
    } finally {
      setLoading(false)
    }
  }

  async function handleAdd() {
    if (isDemo) return
    if (!newWatcher.service_name || !newWatcher.watch_path) {
      toast.error("Please fill in service name and path")
      return
    }
    setAdding(true)
    try {
      await api.watchers.create(newWatcher)
      setNewWatcher({ service_name: "", watch_path: "", env: "production" })
      loadWatchers()
      toast.success("Watcher added")
    } catch (err: any) {
      toast.error(err?.message ?? "Failed to add watcher")
    } finally {
      setAdding(false)
    }
  }

  async function handleToggle(watcher: any) {
    if (isDemo) return
    try {
      await api.watchers.update(watcher.id, { enabled: !watcher.enabled })
      loadWatchers()
    } catch (err: any) {
      toast.error("Failed to update watcher")
    }
  }

  async function handleDelete(id: string) {
    if (isDemo) return
    try {
      await api.watchers.delete(id)
      loadWatchers()
      toast.success("Watcher deleted")
    } catch (err: any) {
      toast.error("Failed to delete watcher")
    }
  }

  return (
    <div className="space-y-4">
      {isDemo && (
        <div className="p-3.5 text-sm border rounded-lg bg-amber-500/10 border-amber-500/20 text-amber-600 dark:text-amber-400 flex items-center gap-2">
          <span className="font-semibold">Demo Mode:</span> Log watchers configuration is read-only.
        </div>
      )}
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Service</TableHead>
              <TableHead>Path</TableHead>
              <TableHead>Env</TableHead>
              <TableHead className="w-[100px]">Enabled</TableHead>
              <TableHead className="w-[100px]"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-8">
                  <div className="flex justify-center text-muted-foreground">
                    <Spinner size="lg" />
                  </div>
                </TableCell>
              </TableRow>
            ) : watchers.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                  No watchers configured.
                </TableCell>
              </TableRow>
            ) : (
              watchers.map((w) => (
                <TableRow key={w.id}>
                  <TableCell className="font-medium">{w.service_name}</TableCell>
                  <TableCell className="font-mono text-xs">{w.watch_path}</TableCell>
                  <TableCell>{w.env}</TableCell>
                  <TableCell>
                    <Switch
                      checked={w.enabled}
                      onCheckedChange={() => handleToggle(w)}
                      disabled={isDemo}
                    />
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(w.id)}
                      disabled={isDemo}
                      className="text-destructive hover:text-destructive hover:bg-destructive/10 disabled:opacity-50"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
            {/* Add Row */}
            <TableRow className="bg-muted/30">
              <TableCell>
                <Input
                  placeholder="Service name"
                  value={newWatcher.service_name}
                  onChange={(e) => setNewWatcher({ ...newWatcher, service_name: e.target.value })}
                  className="h-8"
                  disabled={isDemo}
                />
              </TableCell>
              <TableCell>
                <Input
                  placeholder="/path/to/logs"
                  value={newWatcher.watch_path}
                  onChange={(e) => setNewWatcher({ ...newWatcher, watch_path: e.target.value })}
                  className="h-8"
                  disabled={isDemo}
                />
              </TableCell>
              <TableCell>
                <Input
                  placeholder="production"
                  value={newWatcher.env}
                  onChange={(e) => setNewWatcher({ ...newWatcher, env: e.target.value })}
                  className="h-8"
                  disabled={isDemo}
                />
              </TableCell>
              <TableCell colSpan={2}>
                <Button size="sm" className="w-full h-8" onClick={handleAdd} disabled={adding || isDemo}>
                  {adding ? (
                    <Spinner size="sm" />
                  ) : (
                    <>
                      <Plus className="mr-2 h-4 w-4" />
                      Add
                    </>
                  )}
                </Button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
