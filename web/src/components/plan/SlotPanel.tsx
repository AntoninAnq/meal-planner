"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { WaitingState } from "@/components/plan/WaitingState";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, SelectField } from "@/components/ui/Field";
import { ListRow } from "@/components/ui/ListRow";
import { useRouter } from "@/i18n/navigation";
import { apiGet, apiPost, apiPut } from "@/lib/api/client";
import { ApiError } from "@/lib/api/error";
import type { Alternative, Dish, GuestGroup, LifeStage, MealType } from "@/lib/api/types";

const LIFE_STAGES: LifeStage[] = ["teen_adult", "young_child", "baby"];

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
  const tStage = useTranslations("lifeStage");
  const router = useRouter();

  const [labels, setLabels] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [guests, setGuests] = useState<GuestGroup[]>([]);
  const [guestStage, setGuestStage] = useState<LifeStage>("teen_adult");
  const [guestCount, setGuestCount] = useState(2);
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
    setGuests([]);
    router.refresh();
  }

  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : tCommon("genericError"));
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

  // Same endpoint as the week, a different scope. There is no guests endpoint:
  // two endpoints sharing 90% of their logic always diverge.
  const generateSlot = () =>
    act(async () => {
      setStartedAt(Date.now());
      await apiPost("/meal-plans", {
        scope: { type: "slot", day: date, meal_type: mealType },
        guests,
        constraints: reason ? [reason] : [],
        language: locale,
      });
      refresh();
    });

  return (
    <Dialog open={open} onClose={close} title={t("title", { meal: tMeal(mealType) })}>
      <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div>
          <p className="text-xs tracking-wide text-ink-faint uppercase">{tMeal(mealType)}</p>
          <h2 className="text-lg font-semibold">{t("day", { day: dayOfWeek, date })}</h2>
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

                  {dish.eaters.length > 0 && (
                    <ul className="flex flex-col gap-1.5">
                      {dish.eaters.map((eater) => (
                        <ListRow key={eater.member_id}>
                          {memberNames[eater.member_id] ?? "?"}
                          {eater.serving_variant && (
                            <span className="text-accent"> — {eater.serving_variant}</span>
                          )}
                        </ListRow>
                      ))}
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
                              {alternative.minutes !== null && (
                                <span className="text-xs text-ink-faint">
                                  {" "}
                                  — {alternative.minutes} min
                                </span>
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
                  disabled={busy || !reason.trim()}
                  onClick={() => regenerate(dishes[0])}
                >
                  {t("regenerate")}
                </Button>
              ) : (
                <Button variant="primary" disabled={busy} onClick={generateSlot}>
                  {t("generateSlot")}
                </Button>
              )}
            </section>

            <section className="flex flex-col gap-3 border-t border-border pt-5">
              <div>
                <h3 className="font-medium">{t("guestsHeading")}</h3>
                {/* Transitory: adding your in-laws to the household because
                    they are coming to dinner would skew anti-repetition and
                    portions all year long. */}
                <p className="text-sm text-ink-muted">{t("guestsHint")}</p>
              </div>

              {guests.length > 0 && (
                <ul className="flex flex-col gap-1.5">
                  {guests.map((group, index) => (
                    <ListRow
                      key={`${group.life_stage}-${index}`}
                      action={
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={() =>
                            setGuests((current) => current.filter((_, i) => i !== index))
                          }
                        >
                          {tCommon("remove")}
                        </Button>
                      }
                    >
                      {t("guestRow", { count: group.count, stage: tStage(group.life_stage) })}
                    </ListRow>
                  ))}
                </ul>
              )}

              <div className="flex flex-wrap items-end gap-2">
                <SelectField
                  label={t("guestStage")}
                  value={guestStage}
                  onChange={(event) => setGuestStage(event.target.value as LifeStage)}
                  wrapperClassName="min-w-36 flex-1"
                >
                  {LIFE_STAGES.map((stage) => (
                    <option key={stage} value={stage}>
                      {tStage(stage)}
                    </option>
                  ))}
                </SelectField>
                <Field
                  label={t("guestCount")}
                  type="number"
                  min={1}
                  max={20}
                  value={guestCount}
                  onChange={(event) => setGuestCount(Number(event.target.value))}
                  wrapperClassName="w-24"
                />
                <Button
                  disabled={busy}
                  onClick={() =>
                    setGuests((current) => [
                      ...current,
                      {
                        life_stage: guestStage,
                        count: Math.max(1, Math.min(20, guestCount)),
                        excluded_allergens: [],
                        dislikes: [],
                      },
                    ])
                  }
                >
                  {tCommon("add")}
                </Button>
              </div>

              {guests.length > 0 && (
                <>
                  <p className="text-xs text-ink-faint">{t("guestsNoGuarantee")}</p>
                  <Button variant="primary" disabled={busy} onClick={generateSlot}>
                    {t("generateWithGuests")}
                  </Button>
                </>
              )}
            </section>

            {error && <p className="text-sm text-danger">{error}</p>}
          </>
        )}
      </div>
    </Dialog>
  );
}
