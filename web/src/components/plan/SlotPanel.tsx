"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { VariantConfirm } from "@/components/plan/VariantConfirm";
import { WaitingState } from "@/components/plan/WaitingState";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { ListRow } from "@/components/ui/ListRow";
import { useRouter } from "@/i18n/navigation";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api/client";
import { displayMessage } from "@/lib/api/error";
import type { Alternative, Dish, MealType } from "@/lib/api/types";

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
export function SlotPanel({
  open,
  planId,
  weekStart,
  date,
  dayOfWeek,
  mealType,
  dishes,
  memberNames,
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
  locale: string;
  expectedMs: number;
}) {
  const t = useTranslations("panel");
  const tCommon = useTranslations("common");
  const tMeal = useTranslations("mealType");
  //: The link back to the source is worded once, in `plan`, because the week
  //: view and this panel must not name the same thing two different ways.
  const tPlan = useTranslations("plan");
  const format = useFormatter();
  const router = useRouter();

  const [labels, setLabels] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [alternatives, setAlternatives] = useState<Alternative[] | null>(null);

  const firstDishId = dishes[0]?.id ?? null;

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
    return () => controller.abort();
  }, [open, planId, firstDishId]);

  function close() {
    router.push({ pathname: "/", query: { week: weekStart } });
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
  const choose = (dish: Dish, alternative: Alternative) =>
    act(async () => {
      await apiPut(`/meal-plans/${planId}/dishes/${dish.id}`, {
        recipe_id: alternative.recipe_id,
      });
      refresh();
    });

  const rate = (dish: Dish, value: 1 | -1) =>
    act(async () => {
      // Rating is also an implicit confirmation that the dish was eaten, which
      // fills the history without ever asking anyone to fill in a form.
      await apiPost(`/meal-plans/${planId}/dishes/${dish.id}/rating`, { value });
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

                  {/* First, because it is the cheapest and §6 measured it as
                      the most frequent request: "not that one, show me
                      something else". */}
                  {alternatives !== null && (
                    <section className="flex flex-col gap-2">
                      <div>
                        <h3 className="text-sm font-semibold">{t("alternativesHeading")}</h3>
                        <p className="text-xs text-ink-muted">{t("alternativesHint")}</p>
                      </div>
                      {alternatives.length === 0 ? (
                        <p className="text-sm text-ink-muted">{t("alternativesEmpty")}</p>
                      ) : (
                        <ul className="flex flex-col gap-1.5">
                          {alternatives.map((alternative) => (
                            <ListRow
                              key={alternative.recipe_id}
                              action={
                                <Button
                                  size="sm"
                                  disabled={busy}
                                  onClick={() => choose(dish, alternative)}
                                >
                                  {t("choose")}
                                </Button>
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
                    </section>
                  )}

                  <div className="flex items-center gap-2">
                    <span className="text-sm text-ink-muted">{t("rate")}</span>
                    <Button size="sm" disabled={busy} onClick={() => rate(dish, 1)}>
                      {t("liked")}
                    </Button>
                    <Button size="sm" disabled={busy} onClick={() => rate(dish, -1)}>
                      {t("disliked")}
                    </Button>
                  </div>
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
