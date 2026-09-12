import type { Dish, Invitation, MealPlan, MealType, PlanSlot, Violation } from "@/lib/api/types";

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

/** What is wrong with a meal, in terms of what the household can do about it.
 *
 * Some twenty violation codes exist, and they call for three different
 * reactions. An allergen is the only red. A portion missing for someone who
 * needs an adaptation — today, a baby the model gave no variant — is not a
 * failed meal: the dish is there, one plate is not, and regenerating does not
 * fix it (Haiku wrote no variant on 45 runs out of 45). Everything else is a
 * meal to redo.
 *
 * A slot carries its most serious issue only, so the pill on the card and the
 * banner above the week count the same meals. */
export type IssueKind = "allergen" | "unadapted" | "incomplete";

export type SlotIssue = { kind: IssueKind; names: string[] };

const ALLERGEN_CODES = new Set([
  "allergen_for_eater",
  "allergen_on_planned_dish",
  "unverified_on_planned_dish",
]);
const UNADAPTED_CODES = new Set(["stage_for_eater"]);

export function slotIssue(
  violations: Violation[],
  dishes: Dish[],
  memberNames: Record<string, string>,
): SlotIssue | null {
  if (violations.length === 0) return null;
  if (violations.some((v) => ALLERGEN_CODES.has(v.code))) return { kind: "allergen", names: [] };
  if (violations.some((v) => UNADAPTED_CODES.has(v.code))) {
    // Read off the plate, not off the violation, whose detail is written for
    // the logs: an eater whose assignment only holds through a variant, and
    // whose plate nobody has confirmed, is precisely the one still pending.
    // Confirmation, not the text: writing the portion is optional, deciding
    // the baby can eat is not.
    const names = dishes.flatMap((dish) =>
      dish.eaters
        .filter((eater) => eater.requires_confirmation && eater.variant_confirmed_at === null)
        .map((eater) => memberNames[eater.member_id])
        .filter((name): name is string => Boolean(name)),
    );
    return { kind: "unadapted", names: [...new Set(names)] };
  }
  return { kind: "incomplete", names: [] };
}

export type WeekIssues = Record<IssueKind, { meals: number; names: string[] }>;

/** The banner's counts: meals per issue, and who is missing a portion. */
export function weekIssues(
  violations: Map<SlotKey | "", Violation[]>,
  slots: Map<SlotKey, PlanSlot>,
  memberNames: Record<string, string>,
): WeekIssues {
  const issues: WeekIssues = {
    allergen: { meals: 0, names: [] },
    unadapted: { meals: 0, names: [] },
    incomplete: { meals: 0, names: [] },
  };
  for (const [key, list] of violations) {
    // Plan-level violations point at no meal; the banner words them apart.
    if (key === "") continue;
    const issue = slotIssue(list, slots.get(key)?.dishes ?? [], memberNames);
    if (issue === null) continue;
    const entry = issues[issue.kind];
    entry.meals += 1;
    for (const name of issue.names) if (!entry.names.includes(name)) entry.names.push(name);
  }
  return issues;
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
