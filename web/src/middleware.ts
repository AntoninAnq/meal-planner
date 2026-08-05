import createMiddleware from "next-intl/middleware";

import { routing } from "@/i18n/routing";

export default createMiddleware(routing);

export const config = {
  // `/api` is served by FastAPI through the proxy and must never be rewritten
  // here — that is what keeps the session cookie first-party.
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};
