// Semantics:
//   NEXT_PUBLIC_REPI_PUBLIC = "0"   → public docs-only mode (Vercel landing).
//                                      App routes (/investigations, /config)
//                                      redirect to /repi/docs, "Open
//                                      Investigations" CTA is hidden.
//   anything else (unset, "1", …)   → normal mode. Full app accessible.
//
// Local dev, docker image, and contributors never set this var, so they get
// the full app by default.
export function isPublicMode(): boolean {
  return process.env.NEXT_PUBLIC_REPI_PUBLIC === "0";
}
