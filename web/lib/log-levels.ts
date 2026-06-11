// Single source of truth for log-level badge styling, shared by every panel
// that renders a level (Timeline, CitedChunks, …) so they can't drift apart.
//
// Deliberately minimal palette: theme `destructive` for error-class levels,
// one amber accent for warnings, neutral for INFO and everything else —
// INFO is the overwhelming majority of rows, so colouring it is pure noise.
export function levelTone(level: string | null | undefined): string {
  switch ((level || "").toUpperCase()) {
    case "ERROR":
    case "CRITICAL":
    case "FATAL":
      return "text-destructive border-destructive/30"
    case "WARNING":
    case "WARN":
      return "text-amber-600 dark:text-amber-500 border-amber-500/30"
    default:
      return "text-muted-foreground border-border"
  }
}
