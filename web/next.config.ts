import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  // the repository root has no JS lockfile; pin Turbopack to this app
  turbopack: { root: path.resolve(__dirname) },
};

export default nextConfig;
