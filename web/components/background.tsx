"use client"

import { motion } from "framer-motion"
import { usePathname } from "next/navigation"

interface BackgroundProps {
  /** Force the soft hero glow on. Defaults to auto: on for the docs/landing
   *  page, off everywhere else. Pass `false` to suppress. */
  glow?: boolean
  /** Whether to fade the dot grid toward the edges. Defaults to true. */
  fade?: boolean
}

/**
 * Multi-layer ambient background. Pure CSS gradients + one tiny inline SVG —
 * no images, no canvas. Sits at z-[-10] under everything else so it never
 * intercepts pointer events. Layer order (bottom → top):
 *
 *   1. Base color (the body's own bg-background)
 *   2. Dot grid (28px lattice) softly masked toward the edges
 *   3. Optional ambient glow behind the hero
 *   4. ~2.5% fractal noise so flat fills stop feeling sterile
 */
export function Background({ glow, fade = false }: BackgroundProps) {
  const pathname = usePathname() ?? "/"
  const showGlow = glow ?? pathname.startsWith("/repi")

  return (
    <div
      aria-hidden
      className="fixed inset-0 -z-10 pointer-events-none overflow-hidden"
    >
      <div className={`absolute inset-0 bg-dot-grid ${fade ? "bg-dot-mask" : ""}`} />

      {showGlow && (
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 1.4, ease: "easeOut" }}
          className="absolute left-1/2 -top-[20vh] -translate-x-1/2 w-[80vw] max-w-[1100px] h-[60vh] rounded-full blur-[140px]
                     bg-[radial-gradient(closest-side,oklch(0.68_0.18_265/0.35),transparent_70%)]
                     dark:bg-[radial-gradient(closest-side,oklch(0.55_0.22_275/0.45),transparent_70%)]
                     opacity-60 dark:opacity-80"
        />
      )}

      <div className="absolute inset-0 bg-noise opacity-[0.025] mix-blend-overlay" />
    </div>
  )
}
