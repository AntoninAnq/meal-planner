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

/** What to show for a failed call.
 *
 * The rule is "keep the API's own sentence", and it earns its keep: `422
 * constraint requires a member` is worth more than any wrapper. The one
 * exception is the quota (`ARCHITECTURE.md` §11.7), and it is an exception for
 * a reason of language, not of content — it is the only API refusal a
 * household meets in NORMAL use, so it is the only one that would routinely
 * put an untranslated string in front of someone (§12.1). Every other message
 * reaches a developer far more often than a user.
 */
export function displayMessage(cause: unknown, t: (key: string) => string): string {
  if (!(cause instanceof ApiError)) return t("genericError");
  return cause.status === 429 ? t("quotaExceeded") : cause.message;
}

/** FastAPI puts the message in `detail`, which is a string for our own
 * `HTTPException`s and an array of objects for validation failures.
 *
 * A validation message alone is not actionable: "Input should be a valid
 * dictionary or object to extract fields from" is what a discriminated union
 * says, and it names no field. The API adds `field`; showing it turns an
 * afternoon of guessing into one line. */
export async function messageFrom(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      const first = body.detail[0] as { msg?: unknown; field?: unknown };
      if (typeof first.msg === "string") {
        return typeof first.field === "string" && first.field
          ? `${first.field}: ${first.msg}`
          : first.msg;
      }
    }
  } catch {
    // A non-JSON body (a proxy error page, a truncated response) is not worth
    // surfacing verbatim.
  }
  return fallback;
}
