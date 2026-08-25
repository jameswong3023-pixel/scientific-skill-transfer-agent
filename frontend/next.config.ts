import type { NextConfig } from "next";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://api:8000";

const config: NextConfig = {
  output: "standalone",
  async rewrites() {
    // Same-origin API in the browser: no CORS, and SSE streams pass through cleanly.
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default config;
