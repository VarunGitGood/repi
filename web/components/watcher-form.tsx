"use client"

import { useState, useEffect } from "react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { toast } from "sonner"
import { Plus, Trash2, Loader2 } from "lucide-react"

export function WatcherForm() {
  const [watchers, setWatchers] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [newWatcher, setNewWatcher] = useState({ service_name: "", watch_path: "", env: "production" })

  useEffect(() => {
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
    if (!newWatcher.service_name || !newWatcher.watch_path) {
      toast.error("Please fill in service name and path")
      return
    }
    try {
      await api.watchers.create(newWatcher)
      setNewWatcher({ service_name: "", watch_path: "", env: "production" })
      loadWatchers()
      toast.success("Watcher added")
    } catch (err: any) {
      toast.error("Failed to add watcher")
    }
  }

  async function handleToggle(watcher: any) {
    try {
      await api.watchers.update(watcher.id, { enabled: !watcher.enabled })
      loadWatchers()
    } catch (err: any) {
      toast.error("Failed to update watcher")
    }
  }

  async function handleDelete(id: string) {
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
                  <Loader2 className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
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
                    />
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(w.id)}
                      className="text-destructive hover:text-destructive hover:bg-destructive/10"
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
                />
              </TableCell>
              <TableCell>
                <Input
                  placeholder="/path/to/logs"
                  value={newWatcher.watch_path}
                  onChange={(e) => setNewWatcher({ ...newWatcher, watch_path: e.target.value })}
                  className="h-8"
                />
              </TableCell>
              <TableCell>
                <Input
                  placeholder="production"
                  value={newWatcher.env}
                  onChange={(e) => setNewWatcher({ ...newWatcher, env: e.target.value })}
                  className="h-8"
                />
              </TableCell>
              <TableCell colSpan={2}>
                <Button size="sm" className="w-full h-8" onClick={handleAdd}>
                  <Plus className="mr-2 h-4 w-4" />
                  Add
                </Button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
