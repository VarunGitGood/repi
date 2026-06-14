"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "@/components/brand";

export function Navbar() {
  const pathname = usePathname() || "/";

  // /repi/* routes ship their own self-contained navbar (section anchors,
  // theme toggle, GitHub link). Render nothing here so the two don't stack.
  if (pathname.startsWith("/repi")) return null;

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center max-w-7xl mx-auto px-4">
        <div className="mr-4 flex flex-1">
          <Link
            href="/"
            className="mr-6 flex items-center space-x-2"
          >
            <Brand size={24} />
            <span className="font-bold inline-block">repi</span>
          </Link>
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
        </div>
      </div>
    </header>
  );
}
