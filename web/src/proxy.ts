export { middleware as proxy } from "../middleware";

export const config = {
  matcher: [
    "/",
    "/today/:path*",
    "/holdings/:path*",
    "/reports/:path*",
    "/metrics/:path*",
    "/run/:path*",
  ],
};
