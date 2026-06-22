export { middleware as proxy } from "../middleware";

export const config = {
  matcher: [
    "/",
    "/holdings/:path*",
    "/reports/:path*",
    "/metrics/:path*",
    "/run/:path*",
  ],
};
