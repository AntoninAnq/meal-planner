import { ApiError, messageFrom } from "@/lib/api/error";

/**
 * Writes (and the few reads that must happen after hydration), from the
 * browser.
 *
 * `/api` is same-origin behind the proxy, so the session cookie is sent
 * without CORS, without `SameSite=None`, and without a second hop through
 * Next.js that would only re-wrap the API's error messages.
 */
const BASE = "/api";

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

async function send<T>(
  method: Method,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? {} : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    throw new ApiError(
      response.status,
      await messageFrom(response, `${method} ${path} failed`),
    );
  }
  // 204 on rating, and on any endpoint that has nothing to say.
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const apiGet = <T>(path: string, signal?: AbortSignal) =>
  send<T>("GET", path, undefined, signal);

export const apiPost = <T>(path: string, body?: unknown, signal?: AbortSignal) =>
  send<T>("POST", path, body, signal);

export const apiPut = <T>(path: string, body?: unknown) => send<T>("PUT", path, body);

export const apiPatch = <T>(path: string, body?: unknown) => send<T>("PATCH", path, body);

export const apiDelete = <T>(path: string) => send<T>("DELETE", path);
