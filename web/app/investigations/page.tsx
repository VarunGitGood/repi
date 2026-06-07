"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Play, Sparkles } from "lucide-react"
import { Spinner } from "@/components/ui/spinner"
import { toast } from "sonner"

export default function NewInvestigationPage() {
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(false)
  const router = useRouter()

  async function handleStart() {
    if (!query.trim()) return
    setLoading(true)
    try {
      const res = await api.investigations.create(query)
      router.push(`/investigations/${res.id}`)
    } catch (err: any) {
      toast.error("Failed to start investigation: " + err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      handleStart()
    }
  }

  return (
    <div className="flex flex-col items-center justify-center h-full max-w-2xl mx-auto px-4 pb-20">
      <div className="text-center space-y-4 mb-10">
        <div className="inline-flex items-center justify-center p-3 rounded-2xl bg-primary/10 mb-4">
          <Sparkles className="h-8 w-8 text-primary" />
        </div>
        <h1 className="text-4xl font-extrabold tracking-tight">What's wrong?</h1>
        <p className="text-muted-foreground text-lg">
          Describe the issue you're seeing in the logs. repi will autonomously investigate and find the root cause.
        </p>
      </div>

      <div className="w-full relative">
        <Textarea
          placeholder="e.g. Why are there so many 500 errors in the checkout service in the last hour?"
          className="min-h-[150px] p-6 text-lg resize-none shadow-xl border-border/50 focus-visible:ring-primary/20"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          autoFocus
        />
        <div className="absolute bottom-4 right-4 flex items-center gap-4">
          <span className="text-xs text-muted-foreground hidden sm:block">
            Press <kbd className="px-1 py-0.5 rounded border bg-muted">⌘</kbd> + <kbd className="px-1 py-0.5 rounded border bg-muted">Enter</kbd> to run
          </span>
          <Button 
            size="lg" 
            onClick={handleStart} 
            disabled={loading || !query.trim()}
            className="rounded-full px-8 shadow-lg shadow-primary/20"
          >
            {loading ? (
              <Spinner size="sm" label="Initializing..." />
            ) : (
              <>
                <Play className="mr-2 h-4 w-4 fill-current" />
                Run Investigation
              </>
            )}
          </Button>
        </div>
      </div>

      <div className="mt-12 grid grid-cols-1 sm:grid-cols-3 gap-4 w-full">
        {[
          "Find checkout timeouts in last 6h",
          "Trace user ID 12345 errors",
          "Correlation between auth and DB"
        ].map((example) => (
          <button
            key={example}
            onClick={() => setQuery(example)}
            className="p-3 text-sm text-left rounded-xl border bg-muted/50 hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
          >
            "{example}"
          </button>
        ))}
      </div>
    </div>
  )
}
