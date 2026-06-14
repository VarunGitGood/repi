"use client"

import { useState, useCallback } from "react"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Send } from "lucide-react"
import { DeepResearchToggle } from "./DeepResearchToggle"
import { CommandPicker, getFilteredCommands } from "./CommandPicker"

interface ChatInputProps {
  deepResearch: boolean
  onDeepResearchChange: (next: boolean) => void
  onSend: (query: string, deepResearch: boolean) => void
  onCommand?: (command: string) => void
  disabled?: boolean
  busy?: boolean
}

export function ChatInput({
  deepResearch,
  onDeepResearchChange,
  onSend,
  onCommand,
  disabled,
  busy,
}: ChatInputProps) {
  const [text, setText] = useState("")
  const [pickerIndex, setPickerIndex] = useState(0)

  const isSlash = text.startsWith("/")
  const slashFilter = isSlash ? text.slice(1) : ""
  const showPicker = isSlash && !text.includes(" ")
  const filtered = showPicker ? getFilteredCommands(slashFilter) : []
  const pickerVisible = filtered.length > 0

  const executeCommand = useCallback((cmdName: string) => {
    setText("")
    setPickerIndex(0)
    onCommand?.(cmdName)
  }, [onCommand])

  function submit() {
    const trimmed = text.trim()
    if (!trimmed || disabled) return

    if (trimmed.startsWith("/")) {
      const cmdName = trimmed.slice(1).split(/\s/)[0]
      const match = getFilteredCommands(cmdName).find((c) => c.name === cmdName)
      if (match) {
        executeCommand(match.name)
        return
      }
    }

    onSend(trimmed, deepResearch)
    setText("")
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (pickerVisible) {
      if (e.key === "ArrowDown") {
        e.preventDefault()
        setPickerIndex((i) => Math.min(i + 1, filtered.length - 1))
        return
      }
      if (e.key === "ArrowUp") {
        e.preventDefault()
        setPickerIndex((i) => Math.max(i - 1, 0))
        return
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault()
        executeCommand(filtered[pickerIndex].name)
        return
      }
      if (e.key === "Escape") {
        e.preventDefault()
        setText("")
        return
      }
    }

    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t bg-background p-4">
      <div className="max-w-3xl mx-auto">
        <div className="relative rounded-2xl border border-border shadow-sm focus-within:ring-2 focus-within:ring-primary/20">
          {pickerVisible && (
            <CommandPicker
              filter={slashFilter}
              onSelect={executeCommand}
              onDismiss={() => setText("")}
              activeIndex={pickerIndex}
              onActiveIndexChange={setPickerIndex}
            />
          )}
          <Textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setPickerIndex(0)
            }}
            onKeyDown={onKeyDown}
            placeholder={
              deepResearch
                ? "Describe the incident — Deep Research will run a full multi-step investigation."
                : "Ask about your logs, or type / for commands…"
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
          ⌘/Ctrl + Enter to send · Type / for commands
        </p>
      </div>
    </div>
  )
}
