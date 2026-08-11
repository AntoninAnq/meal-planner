/** Which of the two week views is shown (docs/UX-V0.md §2).
 *
 * Both trees are always rendered; this only decides the `data-view` attribute
 * the CSS reads. `auto` hands the decision to the media query, which is what
 * makes the very first paint correct on any device with no JavaScript.
 */
export type WeekView = "grid" | "list";
export type ViewMode = WeekView | "auto";

/** No `Max-Age`: the cookie dies with the browser session, which is literally
 * what §2 asks for — reopening in grid view the next morning in the kitchen
 * would be counterproductive. Readable server-side, unlike `sessionStorage`,
 * so a reload after toggling never flashes. */
export const VIEW_COOKIE = "mp_week_view";

/** Anything unexpected falls back to `auto` rather than throwing: a mangled
 * cookie is not a reason to fail a page render. */
export function resolveView(cookieValue: string | undefined | null): ViewMode {
  return cookieValue === "grid" || cookieValue === "list" ? cookieValue : "auto";
}

export function viewCookie(view: WeekView): string {
  return `${VIEW_COOKIE}=${view}; Path=/; SameSite=Lax`;
}
