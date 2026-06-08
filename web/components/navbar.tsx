"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { isPublicMode } from "@/lib/public-mode";
import { Brand } from "@/components/brand";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Navbar() {
  const pathname = usePathname() || "/";
  const isPublic = pathname.startsWith("/repi");
  const publicDeploy = isPublicMode();

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center max-w-7xl mx-auto px-4">
        <div className="mr-4 flex flex-1">
          <Link
            href={isPublic ? "/repi/docs" : "/"}
            className="mr-6 flex items-center space-x-2"
          >
            <Brand size={24} />
            <span className="font-bold inline-block">repi</span>
          </Link>
          {!isPublic && (
            <nav className="flex items-center space-x-6 text-sm font-medium">
              <Link
                href="/"
                className="transition-colors hover:text-foreground/80 text-foreground"
              >
                Chat
              </Link>
              <Link
                href="/config"
                className="transition-colors hover:text-foreground/80 text-foreground/60"
              >
                Config
              </Link>
            </nav>
          )}
        </div>
        {isPublic && !publicDeploy && (
          <Link
            href="/"
            className={cn(buttonVariants({ size: "sm" }), "rounded-full")}
          >
            Open Chat
            <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
          </Link>
        )}
      </div>
    </header>
  );
}
