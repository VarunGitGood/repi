"use client"

import { useTheme } from "next-themes"
import { useState, useEffect } from "react"
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter"
import { oneDark, prism } from "react-syntax-highlighter/dist/esm/styles/prism"
import { Copy, Check } from "lucide-react"
import { Button } from "@/components/ui/button"

interface CodeBlockProps {
  code: string
  language?: string
}

export function CodeBlock({ code, language = "bash" }: CodeBlockProps) {
  const { resolvedTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => setMounted(true), [])

  async function handleCopy() {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (!mounted) {
    return (
      <div className="relative rounded-2xl border border-foreground/[0.03] bg-muted/50 overflow-hidden">
        <pre className="font-mono text-[13px] p-6 overflow-x-auto text-muted-foreground/50">{code}</pre>
      </div>
    )
  }

  return (
    <div className="relative rounded-2xl border border-foreground/[0.03] overflow-hidden group bg-card">
      <div className="absolute top-0 left-0 right-0 h-10 bg-muted/30 border-b border-foreground/[0.02] flex items-center px-4 justify-between">
        <div className="flex gap-1.5">
          <div className="size-2.5 rounded-full bg-foreground/5" />
          <div className="size-2.5 rounded-full bg-foreground/5" />
          <div className="size-2.5 rounded-full bg-foreground/5" />
        </div>
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/40 select-none">
          {language}
        </span>
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={handleCopy}
        className="absolute top-1.5 right-1.5 z-10 opacity-0 group-hover:opacity-100 transition-opacity h-7 w-7 hover:bg-foreground/5 rounded-lg"
        aria-label="Copy code"
      >
        {copied ? (
          <Check className="h-3 w-3 text-foreground" />
        ) : (
          <Copy className="h-3 w-3 text-muted-foreground" />
        )}
      </Button>
      <div className="pt-10">
        <SyntaxHighlighter
          language={language}
          style={resolvedTheme === "dark" ? oneDark : prism}
          customStyle={{
            margin: 0,
            background: "transparent",
            borderRadius: 0,
            fontSize: "13px",
            lineHeight: "1.7",
            padding: "1.5rem",
          }}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    </div>
  )
}
