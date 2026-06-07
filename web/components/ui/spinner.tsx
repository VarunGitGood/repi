import { Loader2Icon } from "lucide-react"
import { cn } from "@/lib/utils"

const SIZE_CLASSES = {
  sm: "h-3 w-3",
  md: "h-4 w-4",
  lg: "h-6 w-6",
} as const

type SpinnerSize = keyof typeof SIZE_CLASSES

interface SpinnerProps extends React.HTMLAttributes<HTMLSpanElement> {
  size?: SpinnerSize
  label?: string
}

export function Spinner({ size = "md", label, className, ...props }: SpinnerProps) {
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn("inline-flex items-center gap-2", className)}
      {...props}
    >
      <Loader2Icon className={cn(SIZE_CLASSES[size], "animate-spin")} />
      {label ? <span className="text-sm text-muted-foreground">{label}</span> : (
        <span className="sr-only">Loading</span>
      )}
    </span>
  )
}
