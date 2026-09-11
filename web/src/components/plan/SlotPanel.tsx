"use client";

import { useFormatter, useTranslations } from "next-intl";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { ExclusionToggle } from "@/components/plan/ExclusionButton";
import { FavoriteToggle } from "@/components/plan/FavoriteButton";
import { ReportDish } from "@/components/plan/ReportDish";
import { VariantConfirm } from "@/components/plan/VariantConfirm";
import { WaitingState } from "@/components/plan/WaitingState";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { ListRow } from "@/components/ui/ListRow";
import { useRouter } from "@/i18n/navigation";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api/client";
import { displayMessage } from "@/lib/api/error";
import type { AllergenConflict, Alternative, Dish, Favorite, MealType } from "@/lib/api/types";
import { slotHref } from "@/lib/plan";

/**
 * Screen 5, in a native `<dialog>` driven by the URL.
 *
 * Ordered cheapest first, and V1 reorders it. The alternatives that §6 calls
 * the most frequent case now exist and come first: they are a read, a few tens
 * of milliseconds, no model call. Editing the title by hand comes next, and
 * asking for something else — which costs an LLM call on one slot — last.
 *
 * They are fetched when the panel opens rather than travelling with the plan.
 * A week carries nine slots and nobody opens nine panels; embedding them would
 * make every page load pay for a list almost nobody reads, and the list would
 * go stale on the plan anyway.
 */
/** Both groups of "Autre chose ?" are labelled the same way: the two lists are
 * the same kind of offer, they differ only in where they came from. */
const GROUP = "text-xs font-semibold tracking-[0.06em] text-ink-muted uppercase";

export function SlotPanel({
  open,
  planId,
  weekStart,
  date,
  dayOfWeek,
  mealType,
  dishes,
  memberNames,
  excluded,
  locale,
  expectedMs,
}: {
  open: boolean;
  planId: string | null;
  weekStart: string;
  date: string;
  dayOfWeek: number;
  mealType: MealType;
  dishes: Dish[];
  memberNames: Record<string, string>;
  /** Recipes this household withheld. Read off the page rather than fetched,
   * so the mark and the button agree with the tab after every refresh. */
  excluded: string[];
  locale: string;
  expectedMs: number;
}) {
  const t = useTranslations("panel");
  const tCommon = useTranslations("common");
  const tMeal = useTranslations("mealType");
  //: The link back to the source is worded once, in `plan`, because the week
  //: view and this panel must not name the same thing two different ways.
  const tPlan = useTranslations("plan");
  const tAllergenIn = useTranslations("allergenContains");
  const tAllergenEats = useTranslations("allergenEats");
  const tExclusions = useTranslations("exclusions");
  const format = useFormatter();
  const router = useRouter();
  const pathname = usePathname();

  const [labels, setLabels] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [alternatives, setAlternatives] = useState<Alternative[] | null>(null);
  const [favorites, setFavorites] = useState<Favorite[] | null>(null);
  // Which favourite row has opened its allergen warning. The decision is made
  // in the list, so it is taken in the list: a modal would move it somewhere
  // else and lose the two dishes it is being compared against.
  const [warning, setWarning] = useState<string | null>(null);

  const firstDishId = dishes[0]?.id ?? null;

  // Which recipes on screen are already favourites. Read off the slot list, so
  // a favourite whose source has since been withdrawn is not in it — the toggle
  // then offers to add one that is already there, and the endpoint is
  // idempotent, so the worst case is a button that says the wrong word once.
  const favorited = new Set(
    (favorites ?? []).flatMap((favorite) => (favorite.recipe_id ? [favorite.recipe_id] : [])),
  );
  // A favourite with no recipe is known by its title, as it was written.
  const favoritedTitles = new Set(
    (favorites ?? [])
      .filter((favorite) => favorite.recipe_id === null)
      .map((favorite) => favorite.title),
  );
  const withheld = new Set(excluded);

  // Named, both of them. `recipe_allergen` and `dietary_constraint` give the
  // allergen AND the person, and "this dish contains an allergen" on its own
  // sends the reader off to find out whose it is.
  // Who is eating this dish without an adaptation they need. Derived from the
  // plate rather than stored: `requires_confirmation` already means "this
  // assignment only holds BECAUSE of a variant", so the same member with no
  // variant is precisely the gap.
  //
  // Read ONLY beside `placed_from_favorite`. The same gap appears when the
  // model simply did not write a variant — measured on the first real week,
  // eight slots out of eight — and there it is a generation failure with its
  // own notice, not a consequence of anything the household chose. Saying "ce
  // favori a remplacé la proposition" over it would be a lie.
  const unadapted = (dish: Dish) =>
    dish.eaters.filter((eater) => eater.requires_confirmation && !eater.serving_variant);

  const allergenIn = (conflict: AllergenConflict) =>
    tAllergenIn(conflict.allergen_code as "gluten");
  const whoCannotEat = (conflict: AllergenConflict) =>
    conflict.member_name === null
      ? t("allergenBodyHousehold", { allergen: tAllergenEats(conflict.allergen_code as "gluten") })
      : t("allergenBody", {
          name: conflict.member_name,
          allergen: tAllergenEats(conflict.allergen_code as "gluten"),
        });

  // Read on open, and abandoned if the panel closes first. The request is
  // cheap, but a response landing after the user moved on would set state on a
  // panel that is no longer theirs.
  useEffect(() => {
    if (!open || !planId || !firstDishId) {
      setAlternatives(null);
      return;
    }
    const controller = new AbortController();
    apiGet<Alternative[]>(
      `/meal-plans/${planId}/dishes/${firstDishId}/alternatives`,
      controller.signal,
    )
      .then(setAlternatives)
      .catch(() => setAlternatives([]));
    // `for_slot`: the same predicate the pre-filter uses, so a favourite whose
    // source has since been withdrawn is not offered as a replacement — it
    // stays on the tab, where it can still be removed.
    apiGet<Favorite[]>("/favorites?for_slot=true", controller.signal)
      .then(setFavorites)
      .catch(() => setFavorites([]));
    setWarning(null);
    return () => controller.abort();
  }, [open, planId, firstDishId]);

  // The same shallow write as the card that opened it: closing a panel has
  // nothing to ask the server either.
  function close() {
    window.history.pushState(null, "", slotHref(pathname, weekStart, null));
  }

  function refresh() {
    setStartedAt(null);
    setBusy(false);
    setReason("");
    router.refresh();
  }

  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(displayMessage(cause, tCommon));
      setStartedAt(null);
      setBusy(false);
    }
  }

  const saveLabel = (dish: Dish) =>
    act(async () => {
      await apiPut(`/meal-plans/${planId}/dishes/${dish.id}`, { label: labels[dish.id] });
      refresh();
    });

  // No model call: the candidate was already cleared by the pre-filter, so
  // choosing it is a write and a reload.
  //
  // The two flags travel with the write because only this screen knows what the
  // person was looking at — which list they picked from, and whether a warning
  // was on screen when they did. Both are cleared by any write that does not
  // set them, so nothing lingers from an earlier choice.
  const choose = (
    dish: Dish,
    // A catalogue recipe, or — for a favourite that has none — its title,
    // written onto the plan exactly like one typed by hand.
    target: { recipe_id: string } | { label: string },
    { fromFavorite = false, overrideAllergen = false } = {},
  ) =>
    act(async () => {
      await apiPut(`/meal-plans/${planId}/dishes/${dish.id}`, {
        ...target,
        from_favorite: fromFavorite,
        allergen_override: overrideAllergen,
      });
      setWarning(null);
      refresh();
    });

  const regenerate = (dish: Dish) =>
    act(async () => {
      setStartedAt(Date.now());
      // The stated reason is not friction, it is the value: it becomes a
      // constraint, which is where the negotiation lives.
      await apiPost(`/meal-plans/${planId}/dishes/${dish.id}/regenerate`, { reason });
      refresh();
    });

  // Same endpoint as the week, a different scope — filling an empty slot. The
  // guests case moved out to its own flow (the invitation, screen 3): it needs
  // a day and a meal chosen up front, and it is a thing the household keeps,
  // not a knob on one meal's regeneration.
  const generateSlot = () =>
    act(async () => {
      setStartedAt(Date.now());
      await apiPost("/meal-plans", {
        scope: { type: "slot", day: date, meal_type: mealType },
        // A bare reason, with no interpretation step behind it — the API
        // accepts it as an `other` constraint.
        constraints: reason ? [{ kind: "other", label: reason, detail: null }] : [],
        language: locale,
      });
      refresh();
    });

  // Empties the slot — every dish on it. A household that plans a meal as
  // usual, then has people over, needs the habitual dish to give way; an empty
  // slot is a valid state, a plan is a bank of suggestions (UX-V0 §1).
  const clearSlot = () =>
    act(async () => {
      await apiDelete(`/meal-plans/${planId}/slots/${dayOfWeek}-${mealType}`);
      refresh();
    });

  return (
    <Dialog open={open} onClose={close} title={t("title", { meal: tMeal(mealType) })}>
      <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div>
          {/* `ink-muted`, not `ink-faint`: a label that names which meal you
              are editing is load-bearing, and it sat under 4.5:1. */}
          <p className="text-xs tracking-[0.06em] text-ink-muted uppercase">{tMeal(mealType)}</p>
          {/* "Jeudi 10 septembre", not "2026-09-10": this header is read by a
              person deciding what to cook, and it was printing the ISO string
              the URL travels as. `first-letter` rather than `capitalize`,
              because French does not capitalise the month. */}
          <h2 className="mt-1.5 text-lg leading-[1.2] font-semibold first-letter:uppercase">
            {t("day", {
              date: format.dateTime(new Date(`${date}T12:00:00Z`), {
                weekday: "long",
                day: "numeric",
                month: "long",
              }),
            })}
          </h2>
        </div>
        <Button variant="ghost" size="sm" onClick={close}>
          {t("close")}
        </Button>
      </header>

      <div className="flex flex-1 flex-col gap-6 px-5 py-5">
        {startedAt !== null ? (
          <WaitingState
            startedAt={startedAt}
            expectedMs={expectedMs}
            polling={false}
            onStopWaiting={close}
          />
        ) : (
          <>
            {dishes.length === 0 ? (
              <p className="text-sm text-ink-muted">{t("empty")}</p>
            ) : (
              dishes.map((dish) => (
                <section key={dish.id} className="flex flex-col gap-3">
                  {/* Immediate write, no draft. A plan is not a document: an
                      edit-then-save mechanism would add state, a way to lose
                      changes, and a button, for an object nobody treats as one. */}
                  <div className="flex items-end gap-2">
                    <Field
                      label={t("titleLabel")}
                      value={labels[dish.id] ?? dish.label ?? ""}
                      onChange={(event) =>
                        setLabels((current) => ({ ...current, [dish.id]: event.target.value }))
                      }
                      wrapperClassName="flex-1"
                    />
                    <Button
                      size="md"
                      disabled={busy || (labels[dish.id] ?? dish.label ?? "") === (dish.label ?? "")}
                      onClick={() => saveLabel(dish)}
                    >
                      {t("save")}
                    </Button>
                  </div>

                  {/* Explains the two blocks under it. Without the pill, the
                      missing adaptation reads as a fault rather than as a
                      consequence of what the household chose. */}
                  {(dish.placed_from_favorite || dish.label) && (
                    <div className="flex flex-wrap items-center gap-2">
                      {dish.placed_from_favorite && (
                        <span className="rounded-full border border-border bg-surface-sunken px-2.5 py-1 text-xs font-medium text-ink-body">
                          {t("fromFavorite")}
                        </span>
                      )}
                      {/* The dish stays on this week — withholding is about
                          the weeks to come — so the mark says what changed. */}
                      {dish.recipe_id && withheld.has(dish.recipe_id) && (
                        <span className="rounded-full border border-border bg-surface-sunken px-2.5 py-1 text-xs font-medium text-ink-body">
                          {tExclusions("pill")}
                        </span>
                      )}
                      {/* Any dish with a title. One without a recipe is kept
                          as written — it never becomes one, I7 is about the
                          catalogue — and the tab says what that costs. */}
                      {dish.label && (
                        <FavoriteToggle
                          recipeId={dish.recipe_id}
                          title={dish.label}
                          favorited={
                            dish.recipe_id
                              ? favorited.has(dish.recipe_id)
                              : favoritedTitles.has(dish.label)
                          }
                        />
                      )}
                      {/* Beside the favourite because it is its opposite, and
                          catalogue-only for the same reason: the model writes
                          no dish of its own, so a one-line one never comes
                          back anyway. */}
                      {dish.recipe_id && dish.label && (
                        <ExclusionToggle
                          recipeId={dish.recipe_id}
                          title={dish.label}
                          excluded={withheld.has(dish.recipe_id)}
                        />
                      )}
                    </div>
                  )}

                  {/* Neutral, not red: this is a fact, not an error, and red is
                      reserved. Not `warn-soft` either — "À valider" already
                      occupies that register and the two do not mean the same
                      thing. */}
                  {dish.placed_from_favorite && unadapted(dish).length > 0 && (
                    <div className="rounded-control border border-border bg-surface-sunken px-3.5 py-3">
                      <p className="text-sm font-semibold text-ink">
                        {t("noAdaptationTitle", {
                          name: unadapted(dish)
                            .map((eater) => memberNames[eater.member_id] ?? "?")
                            .join(", "),
                        })}
                      </p>
                      <p className="mt-1 text-[13px] leading-[1.5] text-ink-body">
                        {t("noAdaptationBody")}
                      </p>
                      {/* No "ask for an adaptation" button: nothing regenerates
                          a serving variant on its own, and the one endpoint
                          that could would replace the dish as well. Saying so
                          is better than a control that does something else. */}
                      <p className="mt-1.5 text-[13px] leading-[1.5] text-ink-muted">
                        {t("noAdaptationWay")}
                      </p>
                    </div>
                  )}

                  {/* It survives the click, and it survives the reload. A
                      warning one gesture removes for ever is not a warning —
                      and this meal is on a table four days later, cooked by
                      whoever is free that evening. */}
                  {dish.allergen_override && dish.allergen_conflicts.length > 0 && (
                    <div className="rounded-control border border-danger/30 bg-danger-soft px-3.5 py-3">
                      {dish.allergen_conflicts.map((conflict) => (
                        <div key={`${conflict.allergen_code}-${conflict.member_name ?? ""}`}>
                          <p className="text-sm font-semibold text-danger">
                            {t("allergenTitle", { allergen: allergenIn(conflict) })}
                          </p>
                          <p className="mt-1 text-[13px] leading-[1.5] text-ink-body">
                            {conflict.member_name === null
                              ? t("allergenOverriddenHousehold", {
                                  allergen: tAllergenEats(conflict.allergen_code as "gluten"),
                                })
                              : t("allergenOverridden", {
                                  name: conflict.member_name,
                                  allergen: tAllergenEats(conflict.allergen_code as "gluten"),
                                })}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* One row for everyone eating the dish as it comes, one row
                      per divergence. A row each would repeat three names that
                      say nothing, and bury the one line that does (UX §5). */}
                  {dish.eaters.length > 0 && (
                    <ul className="flex flex-col gap-1.5">
                      {(() => {
                        const plain = dish.eaters.filter((e) => !e.serving_variant);
                        return plain.length > 0 ? (
                          <ListRow>
                            {plain.map((e) => memberNames[e.member_id] ?? "?").join(", ")}
                          </ListRow>
                        ) : null;
                      })()}

                      {dish.eaters
                        .filter((eater) => eater.serving_variant)
                        .map((eater) => {
                          const name = memberNames[eater.member_id] ?? "?";
                          return (
                            <ListRow
                              key={eater.member_id}
                              action={
                                eater.requires_confirmation && planId ? (
                                  <VariantConfirm
                                    planId={planId}
                                    dishId={dish.id}
                                    memberId={eater.member_id}
                                    name={name}
                                    confirmed={eater.variant_confirmed_at !== null}
                                  />
                                ) : undefined
                              }
                            >
                              {name}
                              <span className="text-accent-hover">
                                {" "}
                                — {eater.serving_variant}
                              </span>
                            </ListRow>
                          );
                        })}
                    </ul>
                  )}

                  {/* The end of what is said about THIS dish, before anything
                      that would replace it. Under the suggestions it read as a
                      report about the last one of them. Quiet, because it is
                      rare and changes what every household sees. Only for a
                      catalogue dish: a hand-written one has nothing
                      catalogue-wide to fix. */}
                  {planId && dish.recipe_id && (
                    <ReportDish planId={planId} dishId={dish.id} />
                  )}

                  {/* First, because it is the cheapest and §6 measured it as
                      the most frequent request: "not that one, show me
                      something else". */}
                  {/* Shown before the list arrives, with a placeholder in it:
                      a section that appears a moment after the panel reads as
                      the page jumping, not as something loading. */}
                  {planId && (
                    <section className="flex flex-col gap-3">
                      <div>
                        <h3 className="text-sm font-semibold">{t("alternativesHeading")}</h3>
                        {/* True of both groups below: neither calls the model. */}
                        <p className="text-xs text-ink-muted">{t("alternativesHint")}</p>
                      </div>

                      <div className="flex flex-col gap-1.5">
                        <h4 className={GROUP}>{t("suggestionsHeading")}</h4>
                        {alternatives === null ? (
                          <p className="text-sm text-ink-muted" aria-live="polite">
                            {t("alternativesLoading")}
                          </p>
                        ) : alternatives.length === 0 ? (
                          <p className="text-sm text-ink-muted">{t("alternativesEmpty")}</p>
                        ) : (
                          <ul className="flex flex-col gap-1.5">
                            {alternatives.map((alternative) => (
                              <ListRow
                                key={alternative.recipe_id}
                                action={
                                  <span className="flex flex-none items-center gap-1">
                                    {/* A dish is often favourited before it is
                                        chosen — that is the frequent case, not
                                        the rare one. */}
                                    <FavoriteToggle
                                      recipeId={alternative.recipe_id}
                                      title={alternative.title}
                                      favorited={favorited.has(alternative.recipe_id)}
                                    />
                                    <Button
                                      size="sm"
                                      disabled={busy}
                                      onClick={() =>
                                        choose(dish, { recipe_id: alternative.recipe_id })
                                      }
                                    >
                                      {t("choose")}
                                    </Button>
                                  </span>
                                }
                              >
                                <span className="text-sm">{alternative.title}</span>
                                {/* Worded through `plan.minutes` like everywhere
                                    else: the panel and the grid must not spell
                                    the same duration two different ways. */}
                                {alternative.minutes !== null && (
                                  <span className="text-ink-body">
                                    {" "}
                                    — {tPlan("minutes", { count: alternative.minutes })}
                                  </span>
                                )}
                                {/* Deciding between two dishes on a title alone is
                                    guesswork. This is the one place where reading
                                    the recipe first is the whole point. */}
                                {alternative.source_url && (
                                  <>
                                    {" "}
                                    <a
                                      href={alternative.source_url}
                                      target="_blank"
                                      rel="noreferrer noopener"
                                      aria-label={tPlan("sourceLinkLabel", {
                                        title: alternative.title,
                                      })}
                                      className="text-xs text-ink-muted underline underline-offset-2 hover:text-accent"
                                    >
                                      {tPlan("sourceLink")} ↗
                                    </a>
                                  </>
                                )}
                              </ListRow>
                            ))}
                          </ul>
                        )}
                      </div>

                      {/* Second group, same row shape: one is what the
                          pre-filter had left over, the other is what this
                          household already said it wanted back. A row changing
                          shape between them would read as a different kind of
                          thing. */}
                      {favorites !== null && favorites.length > 0 && (
                        <div className="flex flex-col gap-1.5">
                          <h4 className={GROUP}>
                            {t("favoritesHeading", { count: favorites.length })}
                          </h4>
                          <ul className="flex flex-col gap-1.5">
                            {favorites.map((favorite) => {
                              const key = favorite.recipe_id ?? `title:${favorite.title}`;
                              const target = favorite.recipe_id
                                ? { recipe_id: favorite.recipe_id }
                                : { label: favorite.title };
                              const open = warning === key;
                              const meta = (
                                <>
                                  <span className="text-sm">{favorite.title}</span>
                                  {favorite.recipe_id === null && (
                                    <span className="text-xs text-ink-muted italic">
                                      {" "}
                                      — {tPlan("handWritten")}
                                    </span>
                                  )}
                                  {favorite.minutes !== null && (
                                    <span className="text-ink-body">
                                      {" "}
                                      — {tPlan("minutes", { count: favorite.minutes })}
                                    </span>
                                  )}
                                  {favorite.source_url && (
                                    <>
                                      {" "}
                                      <a
                                        href={favorite.source_url}
                                        target="_blank"
                                        rel="noreferrer noopener"
                                        aria-label={tPlan("sourceLinkLabel", {
                                          title: favorite.title,
                                        })}
                                        className="text-xs text-ink-muted underline underline-offset-2 hover:text-accent"
                                      >
                                        {tPlan("sourceLink")} ↗
                                      </a>
                                    </>
                                  )}
                                </>
                              );

                              // Unfolded in place, and as its own box rather
                              // than inside `ListRow`: that primitive is one
                              // line with one action on the right, which is
                              // exactly what this row stops being. The choice
                              // is made against the rows around it, so the
                              // decision is taken there too — a dialog would
                              // move it somewhere they are not.
                              if (!open) {
                                return (
                                  <ListRow
                                    key={key}
                                    action={
                                      <Button
                                        size="sm"
                                        disabled={busy}
                                        onClick={() =>
                                          // Raised before the write, not after:
                                          // by then the dish is on the plan.
                                          favorite.conflicts.length > 0 ||
                                          favorite.unchecked_allergens
                                            ? setWarning(key)
                                            : choose(dish, target, { fromFavorite: true })
                                        }
                                      >
                                        {t("choose")}
                                      </Button>
                                    }
                                  >
                                    {meta}
                                  </ListRow>
                                );
                              }

                              return (
                                <li
                                  key={key}
                                  className="rounded-control border border-danger/30 bg-danger-soft px-3 py-2.5"
                                >
                                  <p className="text-sm">{meta}</p>

                                  {/* No recipe, so no ingredient list: the
                                      filter has nothing to read, and someone
                                      here has an allergy. */}
                                  {favorite.unchecked_allergens && (
                                    <p className="mt-1.5 text-[13px] leading-[1.5] text-ink-body">
                                      {t("uncheckedAllergens")}
                                    </p>
                                  )}

                                  {favorite.conflicts.map((conflict) => (
                                    <p
                                      key={`${conflict.allergen_code}-${conflict.member_name ?? ""}`}
                                      className="mt-1.5 text-[13px] leading-[1.5]"
                                    >
                                      {/* The allergen AND the person. One
                                          without the other sends the reader
                                          off to check the half that is
                                          missing. */}
                                      <span className="font-semibold text-danger">
                                        {t("allergenTitle", { allergen: allergenIn(conflict) })}
                                      </span>{" "}
                                      <span className="text-ink-body">
                                        {whoCannotEat(conflict)}
                                      </span>
                                    </p>
                                  ))}

                                  <div className="mt-3 flex flex-wrap items-center gap-2">
                                    <Button
                                      size="sm"
                                      variant="danger"
                                      disabled={busy}
                                      onClick={() =>
                                        choose(dish, target, {
                                          fromFavorite: true,
                                          // Only a known conflict is overridden;
                                          // an unchecked title has none to keep.
                                          overrideAllergen: favorite.conflicts.length > 0,
                                        })
                                      }
                                    >
                                      {t("allergenConfirm")}
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => setWarning(null)}
                                    >
                                      {tCommon("cancel")}
                                    </Button>
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                        </div>
                      )}
                    </section>
                  )}
                </section>
              ))
            )}

            <section className="flex flex-col gap-3 border-t border-border pt-5">
              <div>
                <h3 className="font-medium">{t("elseHeading")}</h3>
                <p className="text-sm text-ink-muted">{t("elseHint")}</p>
              </div>
              <Field
                label={t("reasonLabel")}
                placeholder={t("reasonPlaceholder")}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
              {dishes.length > 0 ? (
                <Button
                  variant="primary"
                  className="w-full"
                  disabled={busy || !reason.trim()}
                  onClick={() => regenerate(dishes[0])}
                >
                  {t("regenerate")}
                </Button>
              ) : (
                <Button
                  variant="primary"
                  className="w-full"
                  disabled={busy}
                  onClick={generateSlot}
                >
                  {t("generateSlot")}
                </Button>
              )}
            </section>

            {dishes.length > 0 && planId && (
              <section className="flex flex-col gap-3 border-t border-border pt-5">
                <div>
                  <h3 className="font-medium">{t("clearHeading")}</h3>
                  {/* For when a habitual meal has to give way — people are
                      coming over, and the invitation is composed on screen 3. */}
                  <p className="text-sm text-ink-muted">{t("clearHint")}</p>
                </div>
                <Button variant="danger" disabled={busy} onClick={clearSlot}>
                  {t("clearSlot")}
                </Button>
              </section>
            )}

            {error && <p className="text-sm text-danger">{error}</p>}
          </>
        )}
      </div>
    </Dialog>
  );
}
