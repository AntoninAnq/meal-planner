/** Mirror of the API contract (docs/UX-V0.md §13). Single source of truth.
 *
 * Note what is absent from every shape below: `household_id`. It is derived
 * server-side from the authenticated identity and appears in no payload.
 */

export type LifeStage = "baby" | "young_child" | "teen_adult";

export type MealType = "lunch" | "dinner";

/** Severity decides the SCOPE of the filter, not how bad it feels:
 * a severe allergy excludes the allergen for the whole household. */
export type ConstraintSeverity = "severe_allergy" | "intolerance" | "aversion";

export const ALLERGEN_CODES = [
  "gluten",
  "crustaceans",
  "eggs",
  "fish",
  "peanuts",
  "soybeans",
  "milk",
  "nuts",
  "celery",
  "mustard",
  "sesame",
  "sulphites",
  "lupin",
  "molluscs",
] as const;

export type AllergenCode = (typeof ALLERGEN_CODES)[number];

export type Household = {
  id: string;
  name: string;
};

export type HouseholdSettings = {
  snacks_enabled: boolean;
  max_dishes_soft_limit: number;
  /** Null until the onboarding is finished, including when the answer to the
   * allergy question was "nobody". That answer is exactly what this records. */
  onboarded_at: string | null;
};

export type HouseholdSettingsUpdate = {
  snacks_enabled?: boolean;
  max_dishes_soft_limit?: number;
  /** An intent, not a date: the server stamps its own clock. `false` clears
   * it, which is what makes the onboarding replayable while developing. */
  onboarding_complete?: boolean;
};

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

/** One concept, whose member is optional: a null member means the whole
 * household and is accepted for aversions only. */
export type DietaryConstraint = {
  id: string;
  member_id: string | null;
  allergen_code: AllergenCode | null;
  label: string | null;
  severity: ConstraintSeverity;
  note: string | null;
};

export type MealSlot = {
  day_of_week: number;
  meal_type: MealType;
  enabled: boolean;
};

export type InterpretedConstraint = {
  kind: "time_budget" | "avoid" | "prefer" | "leftover" | "skip_slot" | "other";
  label: string;
  detail?: string | null;
};

export type DishEater = {
  member_id: string;
  /** How to serve this person, never whether they may eat it. */
  serving_variant: string | null;
};

export type DishSource = "catalog" | "llm_suggestion" | "user";

export type Dish = {
  id: string;
  label: string | null;
  recipe_id: string | null;
  /** Always null in V0: overlap is not computable without ingredients. */
  derived_from_dish_id: string | null;
  eaters: DishEater[];
  /** Where it came from. The interface needs it for one thing: a dish someone
   * typed themselves is the only one no filter can vouch for, so it keeps a
   * mark after the global allergen notice disappears (UX §15). */
  source: DishSource;
  /** Declared prep + cooking, and the computed 1..3 rating. Null on the fifth
   * of the catalogue that declares neither — the card then says nothing rather
   * than implying a recipe is quick. */
  minutes: number | null;
  complexity: number | null;
  /** Where the recipe lives, at its source. I9 keeps the facts and sends people
   * to the author for the rest, so this link is not a convenience — it is the
   * half of the bargain the interface owes. Null on a hand-written dish. */
  source_url: string | null;
};

/** A candidate the pre-filter produced and the model passed over.
 *
 * Carries everything the card shows, so choosing one costs no second request.
 * Reading them is free: the ranking is rebuilt from its seed, not stored. */
export type Alternative = {
  recipe_id: string;
  title: string;
  minutes: number | null;
  complexity: number | null;
  ingredients: string[];
  source_url: string | null;
};

/** An anonymous count, never an entity. Guests stay transitory — storing them
 * as members would skew anti-repetition and portions all year long — but a
 * meal cooked for nine that displays as a meal for three is misleading. */
export type SlotGuests = {
  life_stage: LifeStage;
  count: number;
};

export type PlanSlot = {
  day_of_week: number;
  meal_type: MealType;
  dishes: Dish[];
  guests: SlotGuests[];
};

/** Present when the model never produced a plan inside the envelope. The plan
 * is returned anyway, with what is wrong stated plainly — the slot fields are
 * what lets the interface point at it instead of just worrying the user. */
export type Violation = {
  code: string;
  detail: string;
  day_of_week: number | null;
  meal_type: MealType | null;
};

export type MealPlan = {
  id: string;
  week_start: string;
  /** Stamped on every generation. It is what lets a client that stopped
   * waiting tell the plan it was already looking at from the one that has just
   * landed — the endpoint is synchronous and never learns the client left, so
   * abandoning the wait does not abandon the generation. */
  generated_at: string;
  slots: PlanSlot[];
  violations: Violation[];
};

export type WeekScope = { type: "week"; week_start: string };
export type SlotScope = { type: "slot"; day: string; meal_type: MealType };

export type GuestGroup = {
  life_stage: LifeStage;
  count: number;
  /** Excludes the allergen from the WHOLE slot, for everyone. */
  excluded_allergens: AllergenCode[];
  dislikes: string[];
};

export type GeneratePlanRequest = {
  scope: WeekScope | SlotScope;
  member_ids?: string[] | null;
  guests?: GuestGroup[];
  constraints?: string[];
  /** The frontend knows the active locale; the model does not. */
  language?: string;
};
