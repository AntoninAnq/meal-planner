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
  /** What this household reads out when it reports a bug — the head of its own
   * id, made readable. Computed server-side so the screen and the operator's
   * `admin find` cannot disagree about the format. Not a credential: nothing
   * is authorised by knowing it. */
  support_code: string;
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
  kind:
    | "time_budget"
    | "avoid"
    | "prefer"
    | "leftover"
    | "skip_slot"
    | "repeat"
    | "other";
  label: string;
  detail?: string | null;
};

export type DishEater = {
  member_id: string;
  /** How to serve this person, never whether they may eat it. */
  serving_variant: string | null;
  /** True when the assignment only holds BECAUSE of the variant — a baby on a
   * recipe that does not carry that stage (§4.9). No catalogue recipe does, so
   * this is every baby assignment today. Derived server-side, never stored. */
  requires_confirmation: boolean;
  /** When the parent confirmed. Null means "not yet", which is a real state:
   * shown, marked pending, and not a meal to count on. */
  variant_confirmed_at: string | null;
  /** What the variant leaves out, by ingredient name. Checked against the
   * recipe's own list before ever being stored. */
  removals: string[];
};

export type DishSource = "catalog" | "llm_suggestion" | "user";

export type Dish = {
  id: string;
  label: string | null;
  recipe_id: string | null;
  /** The earlier meal of this week built on the same non-pantry ingredients,
   * computed server-side at read time. A claim about a shopping list, never
   * about a saucepan: a shared culinary base lives in the preparation steps,
   * which the catalogue deliberately does not store (I9). Say "the same
   * ingredients", never "the same base". */
  shares_ingredients_with: string | null;
  eaters: DishEater[];
  /** Where it came from. The interface needs it for one thing: a dish someone
   * typed themselves is the only one no filter can vouch for, so it keeps a
   * mark after the global allergen notice disappears (UX §15). */
  source: DishSource;
  /** Put here from the favourites rather than proposed. It is what explains the
   * absence of a serving variant: the favourite replaced the proposal, and
   * nothing recomputed the small portion. */
  placed_from_favorite: boolean;
  /** Somebody was warned this dish carries an allergen and chose it anyway. A
   * warning one click removes for ever is not a warning, and this meal is on a
   * table four days later. */
  allergen_override: boolean;
  /** Filled only when `allergen_override` is set. Recomputed server-side at
   * every read, so an allergy declared afterwards shows up here too. */
  allergen_conflicts: AllergenConflict[];
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

/** An allergen a dish carries that somebody here cannot eat.
 *
 * Computed server-side: `recipe_allergen` says what the dish contains,
 * `dietary_constraint` says who cannot have it, and naming only the allergen
 * would send the reader off to check whose it is. Aversions never appear —
 * red belongs to the allergen and to the irreversible. */
export type AllergenConflict = {
  allergen_code: AllergenCode;
  /** Null on a household-wide constraint, which belongs to nobody in
   * particular. The interface has its own sentence for that rather than
   * inventing a name. */
  member_name: string | null;
};

/** A recipe the household means to cook again.
 *
 * Same shape as `Alternative` on purpose: the slot panel lists the two under
 * two headings, and a row changing shape between the groups would read as a
 * different kind of thing. */
export type Favorite = {
  recipe_id: string;
  title: string;
  minutes: number | null;
  complexity: number | null;
  source_url: string | null;
  /** Empty on the favourites tab, which does not flag allergens by design: a
   * favourite is not a planned meal, and the warning belongs to the moment the
   * dish reaches a plate. */
  conflicts: AllergenConflict[];
  /** Its ingredients were not all recognised, and someone here has an allergy:
   * nothing vouched for what it contains, so choosing it asks first. */
  unchecked_allergens: boolean;
};

/** One ingredient line of a household's own recipe, as the API read it.
 *
 * `ingredient_id` null means nobody recognised the food: the recipe still
 * works — its author knows what they wrote — but it cannot be verified, so it
 * is never proposed on its own and the line lands in "non reconnues" on the
 * shopping list. */
export type RecipeLine = {
  raw: string;
  quantity: string | null;
  unit: string | null;
  ingredient_id: string | null;
  name: string | null;
  /** A heading — "Pour la sauce :" — never counted against the recipe. */
  is_structural: boolean;
};

/** A recipe this household wrote, and where it stands. */
export type HouseholdRecipe = {
  id: string;
  title: string;
  servings: number | null;
  servings_raw: string | null;
  instructions: string | null;
  source_url: string | null;
  lines: RecipeLine[];
  /** Derived, never declared: every line recognised, to foods a person has
   * confirmed. False means "usable, but never proposed on its own". */
  allergens_verified: boolean;
  state: "private" | "pending" | "shared" | "rejected";
  rejected_reason: string | null;
};

/** One food of the referential, offered while someone writes a line. */
export type IngredientMatch = { ingredient_id: string; name: string };

/** A recipe the household never wants proposed again. The other half of a
 * favourite: a recipe is never both, and setting one clears the other. */
export type Exclusion = {
  recipe_id: string;
  title: string;
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

/** A meal with guests, kept beside the plan and never inside it (§4).
 *
 * Guests stay transitory — no member, nothing nominative, a count and a life
 * stage — but unlike `SlotGuests`, which the generation rewrites as a display
 * cache, an invitation is something the household created and comes back to. It
 * survives a regeneration or a cleared slot. `dislikes` is a soft signal, like
 * a household aversion: it nudges the suggestion, it never excludes a dish. */
export type Invitation = {
  id: string;
  week_start: string;
  day_of_week: number;
  meal_type: MealType;
  guests: SlotGuests[];
  dislikes: string[];
};

export type GeneratePlanRequest = {
  scope: WeekScope | SlotScope;
  member_ids?: string[] | null;
  guests?: GuestGroup[];
  /** Structured, like the API. This said `string[]` long after the API stopped
   * accepting strings — nothing referenced it, so nothing failed, and it sat
   * there describing a contract that no longer existed. Kept and corrected
   * rather than deleted: it is what a reader checks first. */
  constraints?: InterpretedConstraint[];
  /** The frontend knows the active locale; the model does not. */
  language?: string;
};


/** When a recipe can be eaten. A quality axis, never a safety one — no member
 * of this union gates the allergen filter. */
export type DishType =
  | "main"
  | "starter"
  | "side"
  | "dessert"
  | "snack"
  | "breakfast"
  | "drink"
  | "component";

/** A recipe nobody has classified, with exactly what is needed to judge it.
 *
 * The rubric is usually the reason it is here: either absent, or one the
 * mapping refuses to read because it groups two different things — `Tartes,
 * Clafoutis` holds an onion tart and a strawberry one. The ingredients are what
 * settle it. */
export type RecipeToType = {
  id: string;
  title: string;
  source_categories: string[];
  source_url: string | null;
  minutes: number | null;
  ingredients: string[];
};

/** Who may run the instance. Two levels, one asymmetry: a `contributor` retags
 * the catalogue, only an `owner` grants — because granting is privilege
 * escalation, and a helper who can add helpers can remove the person who
 * invited them. */
/** One household as an operator needs to see it.
 *
 * `subjects` is what identifies a person here, because nothing else does: no
 * email is stored, by design. `code` is the same string they read in their own
 * settings screen — the only name both sides of a support conversation can say
 * out loud. */
export type AdminHousehold = {
  household_id: string;
  code: string;
  name: string;
  members: number;
  subjects: string[];
  revoked: string[];
  /** Null means "on the rate card", which is why the default is sent alongside
   * rather than left for the reader to remember. */
  limit_override: number | null;
  calls_in_window: number;
};

export type AdminHouseholds = {
  default_limit: number;
  window_hours: number;
  households: AdminHousehold[];
};

export type OperatorLevel = "owner" | "contributor";

export type Operator = {
  auth_subject: string;
  level: OperatorLevel;
  granted_at: string;
  granted_by: string | null;
  /** The code this person reads in their own settings screen, and the only
   * thing about them a human can recognise: `auth_subject` is a twenty-one
   * digit Google identifier. Null when the identity has no live household
   * access, which is blank rather than wrong. */
  support_code: string | null;
};

/** What a household says is wrong with a suggestion — for everyone, not for
 * them. Each one exists because the back office can act on it: `not_a_meal` is
 * retagged, the other two are withdrawn. There is deliberately no "we did not
 * fancy it": that is `Proposer autre chose`, which becomes a constraint on this
 * household instead. */
export type ReportCategory = "not_a_meal" | "dead_link" | "bad_recipe";

/** One recipe households have complained about, grouped: ten reports of the
 * same tart are one decision. */
export type ReportedRecipe = {
  recipe_id: string;
  title: string;
  dish_type: DishType | null;
  source_url: string | null;
  households: number;
  categories: ReportCategory[];
  notes: string[];
};

/** One thing to buy, and how much of it when the source said. */
export type ShoppingLine = {
  name: string;
  /** Null when not one line carried a quantity. A real state, and a different
   * one from zero: the source wrote "du sel". */
  amount: string | null;
};

/** One `FoodCategory`, in the order a shop is walked — decided server-side, in
 * a domain constant, so the screen and the copied text cannot disagree. */
export type ShoppingSection = {
  code: string;
  label: string;
  label_en: string | null;
  lines: ShoppingLine[];
};

export type ShoppingList = {
  week_start: string;
  /** The selection, not the week. */
  meals: number;
  days: number;
  sections: ShoppingSection[];
  /** Names only: nobody checks whether they have 200 g of salt. */
  pantry: string[];
  /** Verbatim. No ingredient, no category, no possible grouping — hiding them
   * makes the list incomplete, folding them in makes it unreadable. */
  unparsed: string[];
  /** A chosen meal holds a dish with no recipe (I7), so its ingredients are not
   * here. Saying nothing would leave a list somebody believes is complete. */
  missing_recipe: boolean;
  /** At least one dish was scaled to the people eating it. */
  scaled: boolean;
  /** Recipes whose quantities are the source's — their yield is not a number
   * of people, or there is none — each with what the source wrote. */
  unscaled: { title: string; servings_raw: string | null }[];
};
