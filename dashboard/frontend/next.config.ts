import type { NextConfig } from "next";

// Two build modes share this one config (PRD §13's pip-installable
// dashboard):
//
// - `npm run dev` (frontend development only, NEXUS_STATIC_EXPORT unset):
//   the dev server runs on 3001, the backend separately on 3002 (see
//   nexus_cli/commands/dashboard.py's history before this became a static
//   export). Rewriting /api/* here means the browser only talks to one
//   origin during dev, avoiding a CORS round-trip for every request.
// - `npm run build` with NEXUS_STATIC_EXPORT=1 (what the hatch build hook in
//   ../../hatch_build.py runs when packaging): produces `out/`, a static
//   SPA that `nexus dashboard` now serves itself alongside its own /api/*
//   routes from ONE process — no Next.js runtime, no Node needed by the
//   end user. Static export doesn't support rewrites() at all (Next errors
//   even in dev if both are set), and doesn't need it: same-origin means
//   `/api/*` just works with no rewrite.
const BACKEND_ORIGIN = process.env.NEXUS_DASHBOARD_BACKEND ?? "http://127.0.0.1:3002";
const STATIC_EXPORT = process.env.NEXUS_STATIC_EXPORT === "1";

const nextConfig: NextConfig = STATIC_EXPORT
  ? { output: "export" }
  : {
      async rewrites() {
        return [
          {
            source: "/api/:path*",
            destination: `${BACKEND_ORIGIN}/api/:path*`,
          },
        ];
      },
    };

export default nextConfig;
