import type { ComponentProps } from "react"
import { Badge } from "@/components/ui/badge"

type BadgeProps = ComponentProps<typeof Badge>

export interface StatusBadgeStyle {
  variant: BadgeProps["variant"]
  className: string
  label: string
}

export function statusBadgeProps(status: string): StatusBadgeStyle {
  switch (status) {
    case "completed":
      return { variant: "default", className: "bg-emerald-500 hover:bg-emerald-600", label: "completed" }
    case "failed":
      return { variant: "destructive", className: "", label: "failed" }
    case "awaiting_clarification":
      return { variant: "outline", className: "border-amber-500 text-amber-500", label: "awaiting clarification" }
    case "running":
    case "started":
      return { variant: "secondary", className: "", label: status }
    default:
      return { variant: "secondary", className: "", label: status.replaceAll("_", " ") }
  }
}
