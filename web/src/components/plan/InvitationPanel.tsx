"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { WaitingState } from "@/components/plan/WaitingState";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, SelectField } from "@/components/ui/Field";
import { ListRow } from "@/components/ui/ListRow";
import { useRouter } from "@/i18n/navigation";
import { apiDelete, apiPost } from "@/lib/api/client";
import { displayMessage } from "@/lib/api/error";
import type { Invitation, LifeStage, MealType, SlotGuests } from "@/lib/api/types";
import { weekDates } from "@/lib/week";

const LIFE_STAGES: LifeStage[] = ["teen_adult", "young_child", "baby"];
const MEAL_TYPES: MealType[] = ["lunch", "dinner"];
const DAYS = [0, 1, 2, 3, 4, 5, 6];

/**
 * The dedicated "someone is coming over" flow, in a `<dialog>` driven by the URL
 * (`?week=…&invite=new` or `&invite=<id>`), so the back button closes it and a
 * reload reopens it (docs/UX-V0.md §14).
 *
 * An invitation is its own thing, kept beside the plan: it is saved first —
 * that is the part the household comes back to — and only then does the same
 * `POST /meal-plans` the week uses generate a proposal for that slot. If the
 * generation fails the invitation still stands, and the slot can be generated
 * again later.
 *
 * There is no separate "generate" button: saving IS asking for the meal. The
 * guests' tastes are a soft signal, exactly like a household aversion — never
 * an allergen filter, which §4 keeps out of this form on purpose.
 */
export function InvitationPanel({
  open,
  weekStart,
  invitation,
  locale,
  expectedMs,
}: {
  open: boolean;
  weekStart: string;
  /** The slot's existing invitation when editing one, null when creating. */
  invitation: Invitation | null;
  locale: string;
  expectedMs: number;
}) {
  const t = useTranslations("invitation");
  const tCommon = useTranslations("common");
  const tMeal = useTranslations("mealType");
  const tStage = useTranslations("lifeStage");
  const router = useRouter();

  const [dayOfWeek, setDayOfWeek] = useState(invitation?.day_of_week ?? 5);
  const [mealType, setMealType] = useState<MealType>(invitation?.meal_type ?? "dinner");
  const [guests, setGuests] = useState<SlotGuests[]>(invitation?.guests ?? []);
  const [guestStage, setGuestStage] = useState<LifeStage>("teen_adult");
  const [guestCount, setGuestCount] = useState(2);
  const [dislikes, setDislikes] = useState((invitation?.dislikes ?? []).join(", "));
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dates = weekDates(weekStart);
  const editing = invitation !== null;

  function dayLabel(index: number): string {
    return new Date(`${dates[index]}T12:00:00Z`).toLocaleDateString(locale, {
      weekday: "long",
      day: "numeric",
      month: "long",
    });
  }

  function close() {
    router.push({ pathname: "/", query: { week: weekStart } });
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

  const parsedDislikes = () =>
    dislikes
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);

  const save = () =>
    act(async () => {
      // The invitation is written first: it is the part that has to survive a
      // failed or later-redone generation.
      await apiPost("/invitations", {
        week_start: weekStart,
        day_of_week: dayOfWeek,
        meal_type: mealType,
        guests,
        dislikes: parsedDislikes(),
      });

      // Then the meal, through the same endpoint the week uses. The tastes ride
      // on every guest group as a soft signal — the party dislikes it, whoever
      // in the party.
      setStartedAt(Date.now());
      await apiPost("/meal-plans", {
        scope: { type: "slot", day: dates[dayOfWeek], meal_type: mealType },
        guests: guests.map((group) => ({
          life_stage: group.life_stage,
          count: group.count,
          excluded_allergens: [],
          dislikes: parsedDislikes(),
        })),
        language: locale,
      });

      setStartedAt(null);
      setBusy(false);
      close();
      router.refresh();
    });

  const remove = () =>
    act(async () => {
      if (!invitation) return;
      // Deleting the invitation leaves the generated meal alone: it may still
      // be a perfectly good dish. Emptying the slot is a separate act, from the
      // slot panel.
      await apiDelete(`/invitations/${invitation.id}`);
      close();
      router.refresh();
    });

  return (
    <Dialog open={open} onClose={close} title={t(editing ? "editTitle" : "createTitle")}>
      <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div>
          <p className="text-xs tracking-wide text-ink-faint uppercase">{t("kicker")}</p>
          <h2 className="text-lg font-semibold">
            {t(editing ? "editTitle" : "createTitle")}
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
            <p className="text-sm text-ink-muted">{t("intro")}</p>

            <div className="flex flex-wrap gap-3">
              <SelectField
                label={t("dayLabel")}
                value={String(dayOfWeek)}
                onChange={(event) => setDayOfWeek(Number(event.target.value))}
                wrapperClassName="min-w-44 flex-1"
              >
                {DAYS.map((index) => (
                  <option key={index} value={index}>
                    {dayLabel(index)}
                  </option>
                ))}
              </SelectField>
              <SelectField
                label={t("mealLabel")}
                value={mealType}
                onChange={(event) => setMealType(event.target.value as MealType)}
                wrapperClassName="min-w-32 flex-1"
              >
                {MEAL_TYPES.map((meal) => (
                  <option key={meal} value={meal}>
                    {tMeal(meal)}
                  </option>
                ))}
              </SelectField>
            </div>

            <section className="flex flex-col gap-3">
              <div>
                <h3 className="font-medium">{t("guestsHeading")}</h3>
                {/* Transitory: they never become members, so the household's
                    everyday menus are untouched by a dinner that happens once. */}
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
                  label={t("countLabel")}
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
                      { life_stage: guestStage, count: Math.max(1, Math.min(20, guestCount)) },
                    ])
                  }
                >
                  {tCommon("add")}
                </Button>
              </div>
            </section>

            <section className="flex flex-col gap-2">
              <div>
                <h3 className="font-medium">{t("tastesHeading")}</h3>
                <p className="text-sm text-ink-muted">{t("tastesHint")}</p>
              </div>
              <Field
                label={t("tastesLabel")}
                placeholder={t("tastesPlaceholder")}
                value={dislikes}
                onChange={(event) => setDislikes(event.target.value)}
              />
            </section>

            <p className="text-xs text-ink-faint">{t("noGuarantee")}</p>

            <div className="flex flex-col gap-2">
              <Button
                variant="primary"
                disabled={busy || guests.length === 0}
                onClick={save}
              >
                {t("save")}
              </Button>
              {editing && (
                <Button variant="danger" disabled={busy} onClick={remove}>
                  {t("remove")}
                </Button>
              )}
            </div>

            {error && <p className="text-sm text-danger">{error}</p>}
          </>
        )}
      </div>
    </Dialog>
  );
}
