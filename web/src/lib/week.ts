/** Week arithmetic, in UTC.
 *
 * Everything here works on `YYYY-MM-DD` strings rather than `Date` objects.
 * A local-time `Date` shifts by a day either side of midnight depending on the
 * viewer's timezone, and "which week is this" would then depend on where you
 * are standing — which is exactly the bug you find in production in October.
 */

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function isIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && toIso(parsed) === value;
}

function toIso(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return toIso(date);
}

/** Monday is day 0 everywhere in this codebase, including in the API's
 * `day_of_week`. `getUTCDay()` calls Sunday 0, hence the shift. */
export function mondayOf(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  const weekday = (date.getUTCDay() + 6) % 7;
  return addDays(iso, -weekday);
}

export function weekDates(weekStart: string): string[] {
  return Array.from({ length: 7 }, (_, index) => addDays(weekStart, index));
}

/** The week comes from the URL so that a reload, the back button and a shared
 * link all land on the same week. A malformed parameter falls back to the
 * current week rather than erroring: a mistyped URL is not worth a 500. */
export function resolveWeek(param: string | string[] | undefined, today: string): string {
  const candidate = Array.isArray(param) ? param[0] : param;
  if (candidate && isIsoDate(candidate)) return mondayOf(candidate);
  return mondayOf(today);
}

export function dayIndexOf(iso: string, weekStart: string): number {
  return weekDates(weekStart).indexOf(iso);
}
