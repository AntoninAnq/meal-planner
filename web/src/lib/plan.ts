import type { Invitation, MealPlan, MealType, PlanSlot, Violation } from "@/lib/api/types";

/** Reading a plan. Pure, so it survives every redesign of the components that
 * display it — which is the point, not the tests. */

export type SlotKey = `${number}-${MealType}`;

export function slotKey(dayOfWeek: number, mealType: MealType): SlotKey {
  return `${dayOfWeek}-${mealType}`;
}

export function parseSlotKey(key: string): { dayOfWeek: number; mealType: MealType } | null {
  const [day, meal] = key.split("-");
  const dayOfWeek = Number(day);
  if (!Number.isInteger(dayOfWeek) || dayOfWeek < 0 || dayOfWeek > 6) return null;
  if (meal !== "lunch" && meal !== "dinner") return null;
  return { dayOfWeek, mealType: meal };
}

/** Where a meal's panel lives, or the bare week when `key` is null. `pathname`
 * is the one in the address bar, locale prefix included: this is written
 * straight into the history, past the locale-aware router. */
export function slotHref(pathname: string, week: string, key: SlotKey | null): string {
  const params = new URLSearchParams({ week });
  if (key !== null) params.set("slot", key);
  return `${pathname}?${params}`;
}

export function slotsByKey(plan: MealPlan | null): Map<SlotKey, PlanSlot> {
  const map = new Map<SlotKey, PlanSlot>();
  for (const slot of plan?.slots ?? []) {
    map.set(slotKey(slot.day_of_week, slot.meal_type), slot);
  }
  return map;
}

/** A violation with no slot would be invisible in the grid, so it is grouped
 * under a bucket the banner can still count. */
export function violationsByKey(violations: Violation[]): Map<SlotKey | "", Violation[]> {
  const map = new Map<SlotKey | "", Violation[]>();
  for (const violation of violations) {
    const key =
      violation.day_of_week === null || violation.meal_type === null
        ? ""
        : slotKey(violation.day_of_week, violation.meal_type);
    map.set(key, [...(map.get(key) ?? []), violation]);
  }
  return map;
}

/** Violations about the plan as a whole carry no slot — there is no single
 * meal to point at — so they need their own sentence rather than being
 * counted as meals that could not be completed. */
export function splitViolations(violations: Violation[]): {
  slot: Violation[];
  plan: Violation[];
} {
  return {
    slot: violations.filter((v) => v.day_of_week !== null && v.meal_type !== null),
    plan: violations.filter((v) => v.day_of_week === null || v.meal_type === null),
  };
}

/** How many MEALS are affected, not how many violations there are.
 *
 * One slot can carry several violations at once — six unserved guests on a
 * single dinner produce six of them — and counting those would announce "six
 * meals could not be completed" for one meal. The user then goes looking for
 * five slots that are perfectly fine.
 */
export function slotsInViolation(violations: Violation[]): number {
  const keys = new Set<string>();
  for (const violation of violations) {
    if (violation.day_of_week === null || violation.meal_type === null) continue;
    keys.add(slotKey(violation.day_of_week, violation.meal_type));
  }
  return keys.size;
}

/** Invitations, addressed the way slots are, because an invitation now takes
 * over the cell of its meal rather than living in a list of its own. Keyed on
 * the week the caller asked for; an invitation from another week never reaches
 * here. */
export function invitationsByKey(invitations: Invitation[]): Map<SlotKey, Invitation> {
  const map = new Map<SlotKey, Invitation>();
  for (const invitation of invitations) {
    map.set(slotKey(invitation.day_of_week, invitation.meal_type), invitation);
  }
  return map;
}

/** Eaters are stored per assignment, so a member appears once per dish. */
export function eaterIds(slot: PlanSlot | undefined): string[] {
  return (slot?.dishes ?? []).flatMap((dish) => dish.eaters.map((eater) => eater.member_id));
}
