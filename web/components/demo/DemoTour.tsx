"use client"

import { AnimatePresence, motion } from "framer-motion"
import { useRouter, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useMemo } from "react"
import { Button } from "@/components/ui/button"
import { ArrowLeft, ArrowRight, Sparkles, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { SeedingStep } from "./steps/SeedingStep"
import { ModesStep } from "./steps/ModesStep"
import { InvestigationStep } from "./steps/InvestigationStep"
import { EvalStep } from "./steps/EvalStep"
import { CloseStep } from "./steps/CloseStep"

export const DEMO_STEPS = ["seeding", "modes", "investigation", "eval", "close"] as const
export type DemoStep = (typeof DEMO_STEPS)[number]

const STEP_LABEL: Record<DemoStep, string> = {
  seeding: "Ingestion pipeline",
  modes: "Two modes",
  investigation: "Deep investigation",
  eval: "Evaluation",
  close: "Wrap up",
}

interface DemoTourProps {
  projectId: string
  onStartInvestigation: () => string | null
  investigationStarted: boolean
  investigationDone: boolean
}

const SPRING = { type: "spring" as const, stiffness: 280, damping: 26 }

export function DemoTour({
  projectId,
  onStartInvestigation,
  investigationStarted,
  investigationDone,
}: DemoTourProps) {
  const router = useRouter()
  const params = useSearchParams()
  const rawStep = parseInt(params.get("step") ?? "0", 10)
  const stepIdx = Number.isFinite(rawStep) ? Math.min(Math.max(rawStep, 0), DEMO_STEPS.length - 1) : 0
  const step = DEMO_STEPS[stepIdx]

  const setStep = useCallback(
    (next: number) => {
      const sp = new URLSearchParams(Array.from(params.entries()))
      sp.set("demo", "1")
      sp.set("step", String(next))
      router.replace(`/?${sp.toString()}`, { scroll: false })
    },
    [params, router],
  )

  const onNext = useCallback(() => {
    if (stepIdx < DEMO_STEPS.length - 1) setStep(stepIdx + 1)
  }, [stepIdx, setStep])
  const onBack = useCallback(() => {
    if (stepIdx > 0) setStep(stepIdx - 1)
  }, [stepIdx, setStep])
  const onSkip = useCallback(() => router.replace("/", { scroll: false }), [router])
  const onRestart = useCallback(() => setStep(0), [setStep])
  const onFreePlay = useCallback(() => router.replace("/", { scroll: false }), [router])

  // Once the investigation is running we dock the card to a corner so the user
  // watches the live ReAct stream in the dashboard underneath. When the SSE
  // stream reports `done`, auto-advance to the eval card after a beat.
  const docked = step === "investigation" && investigationStarted

  useEffect(() => {
    if (step !== "investigation" || !investigationDone) return
    const t = window.setTimeout(() => onNext(), 2800)
    return () => window.clearTimeout(t)
  }, [step, investigationDone, onNext])

  const body = useMemo(() => {
    switch (step) {
      case "seeding":
        return <SeedingStep />
      case "modes":
        return <ModesStep />
      case "investigation":
        return (
          <InvestigationStep
            projectId={projectId}
            onStart={onStartInvestigation}
            done={investigationDone}
            docked={docked}
          />
        )
      case "eval":
        return <EvalStep />
      case "close":
        return <CloseStep onRestart={onRestart} onFreePlay={onFreePlay} />
    }
  }, [step, projectId, onStartInvestigation, investigationDone, docked, onRestart, onFreePlay])

  return (
    <div
      className={cn(
        "fixed inset-0 z-50 flex px-4 pointer-events-none",
        docked ? "items-end justify-end p-4 sm:p-6" : "items-center justify-center",
      )}
    >
      {/* Backdrop only in centered mode — docked mode hands the dashboard back. */}
      <AnimatePresence>
        {!docked && (
          <>
            <motion.div
              key="backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="absolute inset-0 pointer-events-auto bg-background/60 backdrop-blur-[3px]"
            />
            <motion.div
              key="sheen"
              aria-hidden
              initial={{ opacity: 0 }}
              animate={{ opacity: 0.8 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.8 }}
              className="absolute inset-0 pointer-events-none
                         bg-[radial-gradient(ellipse_60%_50%_at_50%_45%,oklch(0.62_0.18_265/0.10),transparent_70%)]
                         dark:bg-[radial-gradient(ellipse_60%_50%_at_50%_45%,oklch(0.55_0.22_275/0.15),transparent_70%)]"
            />
          </>
        )}
      </AnimatePresence>

      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          layout
          initial={{ opacity: 0, y: 14, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -10, scale: 0.97 }}
          transition={{ layout: SPRING, default: SPRING }}
          className={cn(
            "relative pointer-events-auto w-full rounded-2xl border border-border/70",
            "bg-card/95 backdrop-blur-md",
            docked
              ? "max-w-sm shadow-[0_16px_50px_-16px_oklch(0_0_0/0.4)] dark:shadow-[0_16px_50px_-16px_oklch(0_0_0/0.9)] ring-1 ring-primary/20"
              : "max-w-2xl shadow-[0_24px_80px_-20px_oklch(0_0_0/0.35)] dark:shadow-[0_24px_80px_-20px_oklch(0_0_0/0.9)]",
          )}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-border/60">
            <div className="flex items-center gap-2.5">
              <div className="size-6 rounded-md bg-primary/10 flex items-center justify-center">
                <Sparkles className="size-3.5 text-primary" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-[10px] uppercase tracking-[0.18em] font-bold text-muted-foreground">
                  Demo
                </span>
                <span className="text-xs font-medium text-foreground/85">{STEP_LABEL[step]}</span>
                <span className="text-[10px] font-mono text-muted-foreground/70">
                  {stepIdx + 1}/{DEMO_STEPS.length}
                </span>
              </div>
            </div>
            <button
              onClick={onSkip}
              aria-label="Skip demo"
              className="size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            >
              <X className="size-4" />
            </button>
          </div>

          {/* Body */}
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05, duration: 0.3 }}
            className={cn(docked ? "px-4 py-3" : "px-6 py-5")}
          >
            {body}
          </motion.div>

          {/* Footer */}
          <div className="flex items-center justify-between px-5 py-3 border-t border-border/60 bg-muted/20">
            <Button variant="ghost" size="sm" onClick={onBack} disabled={stepIdx === 0}>
              <ArrowLeft className="size-3.5" /> Back
            </Button>
            <div className="flex items-center gap-1.5">
              {DEMO_STEPS.map((_, i) => {
                const isActive = i === stepIdx
                return (
                  <button
                    key={i}
                    onClick={() => setStep(i)}
                    aria-label={`Go to step ${i + 1}`}
                    className="relative h-1.5 rounded-full transition-all duration-200"
                    style={{ width: isActive ? 24 : 6 }}
                  >
                    <span
                      className={
                        "absolute inset-0 rounded-full " +
                        (isActive
                          ? "bg-primary"
                          : "bg-muted-foreground/25 hover:bg-muted-foreground/45")
                      }
                    />
                  </button>
                )
              })}
            </div>
            {stepIdx < DEMO_STEPS.length - 1 ? (
              <Button size="sm" onClick={onNext}>
                Next <ArrowRight className="size-3.5" />
              </Button>
            ) : (
              <Button size="sm" variant="outline" onClick={onFreePlay}>
                Done
              </Button>
            )}
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
