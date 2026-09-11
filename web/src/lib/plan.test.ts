import { describe, expect, it } from "vitest";

import type { Dish, DishEater, Invitation, MealPlan, Violation } from "@/lib/api/types";
import {
  invitationsByKey,
  parseSlotKey,
  slotHref,
  slotKey,
  slotsByKey,
  slotsInViolation,
  splitViolations,
  violationsByKey,
} from "@/lib/plan";

/** A minimal eater. The fields beyond the id exist for the baby variant
 * confirmation (§4.9) and are never what these tests are about. */
function eater(id: string, variant: string | null = null): DishEater {
  return {
    member_id: id,
    serving_variant: variant,
    requires_confirmation: false,
    variant_confirmed_at: null,
    removals: [],
  };
}

function dish(overrides: Partial<Dish> = {}): Dish {
  return {
    id: "d1",
    label: "Poulet aux olives",
    recipe_id: null,
    shares_ingredients_with: null,
    eaters: [eater("m1")],
    source: "catalog",
    minutes: null,
    complexity: null,
    source_url: null,
    placed_from_favorite: false,
    allergen_override: false,
    allergen_conflicts: [],
    ...overrides,
  };
}

const PLAN: MealPlan = {
  id: "p1",
  week_start: "2026-08-10",
  generated_at: "2026-08-11T10:00:00Z",
  slots: [
    { day_of_week: 0, meal_type: "dinner", dishes: [dish()], guests: [] },
    { day_of_week: 3, meal_type: "lunch", dishes: [dish({ id: "d2" })], guests: [] },
  ],
  violations: [],
};

describe("slotKey", () => {
  it("round-trips", () => {
    expect(parseSlotKey(slotKey(3, "dinner"))).toEqual({ dayOfWeek: 3, mealType: "dinner" });
  });

  it("rejects a key that is not a slot", () => {
    // These arrive from the URL, so they are attacker-controlled in practice.
    expect(parseSlotKey("9-dinner")).toBeNull();
    expect(parseSlotKey("3-brunch")).toBeNull();
    expect(parseSlotKey("dinner")).toBeNull();
    expect(parseSlotKey("")).toBeNull();
  });
});

describe("slotHref", () => {
  it("opens a meal over the week it belongs to", () => {
    expect(slotHref("/fr", "2026-09-07", "3-dinner")).toBe("/fr?week=2026-09-07&slot=3-dinner");
  });

  it("closes back onto that same week", () => {
    expect(slotHref("/fr", "2026-09-07", null)).toBe("/fr?week=2026-09-07");
  });
});

describe("slotsByKey", () => {
  it("indexes the filled slots", () => {
    const map = slotsByKey(PLAN);
    expect(map.get("0-dinner")?.dishes).toHaveLength(1);
    expect(map.get("3-lunch")).toBeDefined();
    expect(map.get("1-dinner")).toBeUndefined();
  });

  it("handles the absence of a plan, which is a monday morning, not an error", () => {
    expect(slotsByKey(null).size).toBe(0);
  });
});

describe("invitationsByKey", () => {
  const invitation = (id: string, day: number, meal: "lunch" | "dinner"): Invitation => ({
    id,
    week_start: "2026-09-07",
    day_of_week: day,
    meal_type: meal,
    guests: [{ life_stage: "teen_adult", count: 4 }],
    dislikes: [],
  });

  it("addresses an invitation the way a slot is addressed", () => {
    const map = invitationsByKey([invitation("i1", 5, "dinner")]);
    expect(map.get("5-dinner")?.id).toBe("i1");
    expect(map.get("5-lunch")).toBeUndefined();
  });

  it("is empty when nobody is coming, which is most weeks", () => {
    expect(invitationsByKey([]).size).toBe(0);
  });
});

describe("violationsByKey", () => {
  const violations: Violation[] = [
    { code: "eater_not_served", detail: "…", day_of_week: 3, meal_type: "dinner" },
    { code: "too_many_dishes", detail: "…", day_of_week: 3, meal_type: "dinner" },
    { code: "missing_slot", detail: "…", day_of_week: 5, meal_type: "lunch" },
  ];

  it("groups them by the slot the interface has to mark", () => {
    const map = violationsByKey(violations);
    expect(map.get("3-dinner")).toHaveLength(2);
    expect(map.get("5-lunch")).toHaveLength(1);
  });

  it("keeps a slot-less violation countable instead of dropping it", () => {
    const map = violationsByKey([{ code: "odd", detail: "…", day_of_week: null, meal_type: null }]);
    expect(map.get("")).toHaveLength(1);
  });
});

describe("splitViolations", () => {
  it("keeps the two failures apart", () => {
    // A plan-level violation points at no meal: counting it as "a meal could
    // not be completed" would send the user hunting for a slot that is fine.
    const { slot, plan } = splitViolations([
      { code: "eater_not_served", detail: "…", day_of_week: 3, meal_type: "dinner" },
      { code: "degenerate_plan", detail: "…", day_of_week: null, meal_type: null },
    ]);
    expect(slot.map((v) => v.code)).toEqual(["eater_not_served"]);
    expect(plan.map((v) => v.code)).toEqual(["degenerate_plan"]);
  });
});

describe("slotsInViolation", () => {
  it("counts meals, not violations", () => {
    // Six unserved guests on one dinner are six violations and ONE meal.
    // Announcing "six meals" sends the user hunting for five that are fine.
    const guests: Violation[] = Array.from({ length: 6 }, (_, i) => ({
      code: "eater_not_served",
      detail: `g1_${i} eats nothing`,
      day_of_week: 5,
      meal_type: "dinner",
    }));
    expect(slotsInViolation(guests)).toBe(1);
  });

  it("counts each affected meal once", () => {
    expect(
      slotsInViolation([
        { code: "a", detail: "", day_of_week: 5, meal_type: "dinner" },
        { code: "b", detail: "", day_of_week: 5, meal_type: "lunch" },
        { code: "c", detail: "", day_of_week: 2, meal_type: "dinner" },
      ]),
    ).toBe(3);
  });

  it("ignores plan-level violations, which point at no meal", () => {
    expect(
      slotsInViolation([{ code: "degenerate_plan", detail: "", day_of_week: null, meal_type: null }]),
    ).toBe(0);
  });
});
