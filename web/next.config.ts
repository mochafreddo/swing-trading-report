import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(process.env.SAB_SKIP_ROOT_ENV === "1" &&
  process.env.SAB_PORTFOLIO_R2_FIXTURE === "1"
    ? { distDir: ".next-portfolio-fixture" }
    : {}),
};

export default nextConfig;
