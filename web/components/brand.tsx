import Image from "next/image"
import { cn } from "@/lib/utils"

interface BrandProps {
  size?: number
  className?: string
}

export function Brand({ size = 24, className }: BrandProps) {
  return (
    <Image
      src="/repi.png"
      alt="repi"
      width={size}
      height={size}
      priority
      className={cn("shrink-0", className)}
    />
  )
}
