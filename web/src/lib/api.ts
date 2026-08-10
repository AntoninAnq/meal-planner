import { cookies } from "next/headers";

/**
 * Server-side API access.
 *
 * Single origin behind the proxy: `/api` is
 * same-origin for the browser, and Server Components reach the API container
 * directly. Neither path ever sends a `household_id` — it is derived from the
 * session on the API side (invariant I6).
 */
const INTERNAL_API_BASE = process.env.INTERNAL_API_BASE_URL ?? "http://api:8000";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

export async function apiGet<T>(path: string): Promise<T | null> {
  const cookieHeader = (await cookies()).toString();

  const response = await fetch(`${INTERNAL_API_BASE}${path}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });

  // Not signed in, or signed in without a household yet: the caller renders the
  // signed-out view rather than treating it as a failure.
  if (response.status === 401 || response.status === 403) {
    return null;
  }
  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} failed`);
  }
  return (await response.json()) as T;
}

export type Household = {
  id: string;
  name: string;
};

export type LifeStage = "baby" | "young_child" | "teen_adult";

export type Member = {
  id: string;
  display_name: string;
  birth_date: string | null;
  life_stage: LifeStage;
};

export type PendingTransition = {
  member_id: string;
  current: LifeStage;
  proposed: LifeStage;
};
