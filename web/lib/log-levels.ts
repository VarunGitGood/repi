export type NormalisedLevel = "INFO" | "WARN" | "ERROR"

export function normalizeLevel(level: string | null | undefined): NormalisedLevel {
  switch ((level || "").toUpperCase()) {
    case "ERROR":
    case "CRITICAL":
    case "FATAL":
      return "ERROR"
    case "WARN":
    case "WARNING":
      return "WARN"
    default:
      return "INFO"
  }
}

export function levelTone(level: string | null | undefined): string {
  switch (normalizeLevel(level)) {
    case "ERROR":
      return "text-destructive border-destructive/30"
    case "WARN":
      return "text-amber-600 dark:text-amber-500 border-amber-500/30"
    case "INFO":
    default:
      return "text-blue-600 dark:text-blue-400 border-blue-500/30"
  }
}
