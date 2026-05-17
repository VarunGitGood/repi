"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Terminal } from "lucide-react";

export function Navbar() {
  const pathname = usePathname() || "/";
  // /repi/* is treated as public — docs, future demo, marketing.
  const isPublic = pathname.startsWith("/repi");

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center max-w-7xl mx-auto px-4">
        <div className="mr-4 flex">
          <Link
            href={isPublic ? "/repi/docs" : "/investigations"}
            className="mr-6 flex items-center space-x-2"
          >
            <Terminal className="h-6 w-6 text-primary" />
            <span className="font-bold inline-block">repi</span>
          </Link>
          {!isPublic && (
            <nav className="flex items-center space-x-6 text-sm font-medium">
              <Link
                href="/investigations"
                className="transition-colors hover:text-foreground/80 text-foreground"
              >
                Investigations
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
      </div>
    </header>
  );
}
