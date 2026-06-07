"use client"

import { useState, useEffect } from "react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
import { Save, Eye, EyeOff } from "lucide-react"
import { Spinner } from "@/components/ui/spinner"

export function ConfigForm() {
  const [config, setConfig] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [showKey, setShowKey] = useState(false)

  useEffect(() => {
    loadConfig()
  }, [])

  async function loadConfig() {
    try {
      const data = await api.config.get()
      setConfig(data)
    } catch (err: any) {
      toast.error("Failed to load config: " + err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    setSaving(true)
    try {
      await api.config.update(config)
      toast.success("Settings saved and reloaded")
    } catch (err: any) {
      toast.error("Failed to save: " + err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground">
        <Spinner size="lg" label="Loading config..." />
      </div>
    )
  }
  if (!config) return <div>Error loading config.</div>

  const handleChange = (key: string, value: any) => {
    setConfig((prev: any) => ({ ...prev, [key]: value }))
  }

  return (
    <div className="space-y-8">
      <div className="grid gap-6 md:grid-cols-2">
        {/* Database & Redis */}
        <Card>
          <CardHeader>
            <CardTitle>Infrastructure</CardTitle>
            <CardDescription>Database and Cache settings. Changes to DB URL may require restart.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="DATABASE_URL">Database URL</Label>
              <Input
                id="DATABASE_URL"
                value={config.DATABASE_URL}
                onChange={(e) => handleChange("DATABASE_URL", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="REDIS_URL">Redis URL</Label>
              <Input
                id="REDIS_URL"
                value={config.REDIS_URL}
                onChange={(e) => handleChange("REDIS_URL", e.target.value)}
              />
            </div>
            <div className="flex items-center space-x-2">
              <Switch
                id="ENABLE_REDIS_CACHE"
                checked={config.ENABLE_REDIS_CACHE}
                onCheckedChange={(val) => handleChange("ENABLE_REDIS_CACHE", val)}
              />
              <Label htmlFor="ENABLE_REDIS_CACHE">Enable Redis Cache</Label>
            </div>
          </CardContent>
        </Card>

        {/* LLM Settings */}
        <Card>
          <CardHeader>
            <CardTitle>LLM Provider</CardTitle>
            <CardDescription>Configure your primary AI model for investigation.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="LLM_PROVIDER">Provider</Label>
              <select
                id="LLM_PROVIDER"
                className="w-full h-10 px-3 py-2 text-sm border rounded-md bg-background"
                value={config.LLM_PROVIDER}
                onChange={(e) => handleChange("LLM_PROVIDER", e.target.value)}
              >
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="mistral">Mistral</option>
                <option value="gemini">Gemini</option>
                <option value="ollama">Ollama</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="LLM_MODEL">Model</Label>
              <Input
                id="LLM_MODEL"
                value={config.LLM_MODEL || ""}
                placeholder="e.g. gpt-4o, claude-3-sonnet"
                onChange={(e) => handleChange("LLM_MODEL", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="LLM_API_KEY">API Key</Label>
              <div className="relative">
                <Input
                  id="LLM_API_KEY"
                  type={showKey ? "text" : "password"}
                  value={config.LLM_API_KEY || ""}
                  onChange={(e) => handleChange("LLM_API_KEY", e.target.value)}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  className="absolute right-0 top-0 h-full px-3 py-2"
                  onClick={() => setShowKey(!showKey)}
                >
                  {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Investigation Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Investigation</CardTitle>
            <CardDescription>Tune the ReAct loop and time window expansion.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="TIME_WINDOW_INITIAL_MINUTES">Initial Window (min)</Label>
              <Input
                id="TIME_WINDOW_INITIAL_MINUTES"
                type="number"
                value={config.TIME_WINDOW_INITIAL_MINUTES}
                onChange={(e) => handleChange("TIME_WINDOW_INITIAL_MINUTES", parseInt(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="TIME_WINDOW_EXPANSIONS">Expansion Sequence</Label>
              <Input
                id="TIME_WINDOW_EXPANSIONS"
                value={config.TIME_WINDOW_EXPANSIONS}
                placeholder="e.g. 60,360,1440"
                onChange={(e) => handleChange("TIME_WINDOW_EXPANSIONS", e.target.value)}
              />
            </div>
            <div className="flex items-center space-x-2">
              <Switch
                id="AUTO_DELETE_OLD_INVESTIGATIONS"
                checked={config.AUTO_DELETE_OLD_INVESTIGATIONS}
                onCheckedChange={(val) => handleChange("AUTO_DELETE_OLD_INVESTIGATIONS", val)}
              />
              <Label htmlFor="AUTO_DELETE_OLD_INVESTIGATIONS">Auto-delete old investigations</Label>
            </div>
          </CardContent>
        </Card>

        {/* Worker Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Worker</CardTitle>
            <CardDescription>Background process configuration.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="WATCHER_CONFIG_REFRESH_SECS">Watcher Refresh (secs)</Label>
              <Input
                id="WATCHER_CONFIG_REFRESH_SECS"
                type="number"
                value={config.WATCHER_CONFIG_REFRESH_SECS}
                onChange={(e) => handleChange("WATCHER_CONFIG_REFRESH_SECS", parseInt(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="MAX_RETRIES_PER_STEP">Max Retries per Step</Label>
              <Input
                id="MAX_RETRIES_PER_STEP"
                type="number"
                value={config.MAX_RETRIES_PER_STEP}
                onChange={(e) => handleChange("MAX_RETRIES_PER_STEP", parseInt(e.target.value))}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="flex justify-end pt-4">
        <Button size="lg" onClick={handleSave} disabled={saving}>
          {saving ? (
            <Spinner size="sm" label="Saving..." />
          ) : (
            <>
              <Save className="mr-2 h-4 w-4" />
              Save Settings
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
