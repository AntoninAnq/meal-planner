import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  // The app is served behind the reverse proxy on a single origin
  //, so it never needs to know an API host: `/api`
  // is same-origin. Nothing here should ever hardcode a backend address.
  output: "standalone",
};

export default withNextIntl(nextConfig);
