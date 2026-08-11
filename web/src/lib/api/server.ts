import "server-only";

import { cookies } from "next/headers";

import { ApiError, messageFrom } from "@/lib/api/error";

/**
 * Reads, from Server Components only.
 *
 * Server Components reach the API container directly; the browser only ever
 * talks to `/api` on the single public origin. Neither path sends a
 * `household_id` — it is derived from the session on the API side.
 */
const INTERNAL_API_BASE = process.env.INTERNAL_API_BASE_URL ?? "http://api:8000";

/** Returns null when there is no session or no household yet, so callers can
 * render the signed-out view instead of treating it as a failure. */
export async function apiGet<T>(path: string): Promise<T | null> {
  const cookieHeader = (await cookies()).toString();

  const response = await fetch(`${INTERNAL_API_BASE}${path}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });

  if (response.status === 401 || response.status === 403) {
    return null;
  }
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, await messageFrom(response, `GET ${path} failed`));
  }
  return (await response.json()) as T;
}
