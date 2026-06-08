"use client"

import { useState } from "react"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Send } from "lucide-react"
import { DeepResearchToggle } from "./DeepResearchToggle"

interface ChatInputProps {
  deepResearch: boolean
  onDeepResearchChange: (next: boolean) => void
  onSend: (query: string, deepResearch: boolean) => void
  disabled?: boolean
  busy?: boolean
}

export function ChatInput({
  deepResearch,
  onDeepResearchChange,
  onSend,
  disabled,
  busy,
}: ChatInputProps) {
  const [text, setText] = useState("")

  function submit() {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed, deepResearch)
    setText("")
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t bg-background p-4">
      <div className="max-w-3xl mx-auto">
        <div className="relative rounded-2xl border border-border shadow-sm focus-within:ring-2 focus-within:ring-primary/20">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={
              deepResearch
                ? "Describe the incident — Deep Research will run a full multi-step investigation."
                : "Ask a quick question about the logs (e.g. 'errors in auth-svc last 24 hours')…"
            }
            className="min-h-[80px] max-h-[280px] resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 p-4 pb-14"
            disabled={disabled}
            autoFocus
          />
          <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between">
            <DeepResearchToggle on={deepResearch} onChange={onDeepResearchChange} />
            <Button
              size="sm"
              onClick={submit}
              disabled={disabled || !text.trim()}
              className="rounded-full"
            >
              {busy ? (
                <Spinner size="sm" label="…" />
              ) : (
                <>
                  <Send className="h-3.5 w-3.5 mr-1.5" />
                  Send
                </>
              )}
            </Button>
          </div>
        </div>
        <p className="mt-2 text-center text-xs text-muted-foreground">
          ⌘/Ctrl + Enter to send · Deep Research toggle persists across turns
        </p>
      </div>
    </div>
  )
}
