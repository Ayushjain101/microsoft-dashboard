import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    inlineCss: true,
  },
  headers: async () => [
    {
      // Prevent browsers from caching HTML pages across deploys
      source: "/((?!_next/static|favicon.ico).*)",
      headers: [
        { key: "Cache-Control", value: "no-cache, must-revalidate" },
      ],
    },
  ],
};

export default nextConfig;
