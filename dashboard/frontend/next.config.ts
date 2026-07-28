import type { NextConfig } from "next";

// The dashboard backend runs separately (`nexus dashboard` launches it on
// 127.0.0.1:3002, see nexus_cli/commands/dashboard.py). Rewriting /api/*
// here means the browser only ever talks to this origin (3001), avoiding
// a second CORS round-trip for every request.
const BACKEND_ORIGIN = process.env.NEXUS_DASHBOARD_BACKEND ?? "http://127.0.0.1:3002";

const nextConfig: NextConfig = {
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
