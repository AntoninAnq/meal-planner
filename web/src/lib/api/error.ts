/** Carries the API's own message rather than a re-wrapped one.
 *
 * This is the reason writes go straight to `/api` from the browser instead of
 * through a Server Action: when the API answers `422 constraint requires a
 * member`, that is the sentence worth showing.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** FastAPI puts the message in `detail`, which is a string for our own
 * `HTTPException`s and an array of objects for validation failures. */
export async function messageFrom(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      const first = body.detail[0] as { msg?: unknown };
      if (typeof first.msg === "string") return first.msg;
    }
  } catch {
    // A non-JSON body (a proxy error page, a truncated response) is not worth
    // surfacing verbatim.
  }
  return fallback;
}
