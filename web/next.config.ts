import type { NextConfig } from "next";

// When the UI is shipped in the combined container the browser only talks to
// the Next.js server on port 3000. Calls to `/api/*` get proxied to uvicorn on
// localhost:8000 by default; override via REPI_API_INTERNAL_URL when the API
// lives in a sibling container or off-host.
const apiTarget =
  process.env.REPI_API_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // No <Image> usage in the app — disabling optimization lets Next's standalone
  // tracer drop `sharp` + libvips (~33 MB) from the production bundle.
  images: { unoptimized: true },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiTarget}/:path*`,
      },
    ];
  },
};

export default nextConfig;
