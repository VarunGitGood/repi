import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// NEXT_PUBLIC_REPI_PUBLIC === "0" → public/docs-only deploy: every app route
// redirects to /repi/docs. Anything else (unset, "1") leaves the app intact.
export function middleware(req: NextRequest) {
  if (process.env.NEXT_PUBLIC_REPI_PUBLIC === "0") {
    return NextResponse.redirect(new URL("/repi/docs", req.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/investigations/:path*", "/config/:path*"],
};
