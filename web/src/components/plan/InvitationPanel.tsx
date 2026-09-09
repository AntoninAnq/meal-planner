"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { WaitingState } from "@/components/plan/WaitingState";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useRouter } from "@/i18n/navigation";
import { apiDelete, apiPost } from "@/lib/api/client";
import { displayMessage } from "@/lib/api/error";
import { cx } from "@/lib/cx";
import type { Invitation, LifeStage, MealType, SlotGuests } from "@/lib/api/types";
import { weekDates } from "@/lib/week";

/** Oldest first, which is the order the counters read in. */
const LIFE_STAGES: LifeStage[] = ["teen_adult", "young_child", "baby"];
const MEAL_TYPES: MealType[] = ["lunch", "dinner"];
const DAYS = [0, 1, 2, 3, 4, 5, 6];
const MAX_PER_STAGE = 20;

type Counts = Record<LifeStage, number>;

function countsOf(guests: SlotGuests[]): Counts {
  const counts: Counts = { teen_adult: 0, young_child: 0, baby: 0 };
  for (const group of guests) counts[group.life_stage] += group.count;
  return counts;
}

/** One chip in a radio group. A `<label>` around a visually hidden radio, so
 * arrow keys, the tab stop and the announced role all come from the platform
 * rather than from `aria-*` bolted onto a button. */
function Chip({
  name,
  checked,
  onSelect,
  className,
  children,
}: {
  name: string;
  checked: boolean;
  onSelect: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="min-w-0 cursor-pointer">
      <input
        type="radio"
        name={name}
        checked={checked}
        onChange={onSelect}
        className="peer sr-only"
      />
      <span
        className={cx(
          "block rounded-control border text-center transition-colors",
          "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent",
          checked
            ? "border-guest bg-guest-soft text-guest"
            : "border-border bg-surface-raised text-ink-muted hover:border-border-strong",
          className,
        )}
      >
        {children}
      </span>
    </label>
  );
}

/** A step of the form. Numbered, because the three answers are asked in an
 * order and the middle one is the only one that is not obvious. */
function Step({
  index,
  heading,
  aside,
  children,
}: {
  index: number;
  heading: string;
  aside?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="mb-2.5 text-xs font-medium tracking-[0.04em] text-ink-muted uppercase">
        {index} · {heading}
        {aside && <span className="ml-1.5 normal-case tracking-normal">{aside}</span>}
      </h3>
      {children}
    </section>
  );
}

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
 *
 * Everything here is chosen by tapping. Two selects, a stage picker, a number
 * field and an Add button used to stand between the household and a dinner
 * they had already decided on; the day, the meal and the three counts are all
 * one tap each now, and nothing is typed but the tastes.
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
  const format = useFormatter();
  const router = useRouter();

  const [dayOfWeek, setDayOfWeek] = useState(invitation?.day_of_week ?? 5);
  const [mealType, setMealType] = useState<MealType>(invitation?.meal_type ?? "dinner");
  const [counts, setCounts] = useState<Counts>(countsOf(invitation?.guests ?? []));
  const [dislikes, setDislikes] = useState<string[]>(invitation?.dislikes ?? []);
  const [draft, setDraft] = useState("");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dates = weekDates(weekStart);
  const editing = invitation !== null;
  const total = LIFE_STAGES.reduce((sum, stage) => sum + counts[stage], 0);

  const day = (index: number) => new Date(`${dates[index]}T12:00:00Z`);

  // Only the stages someone actually brought. A group of zero is not a group.
  const guests = (): SlotGuests[] =>
    LIFE_STAGES.filter((stage) => counts[stage] > 0).map((stage) => ({
      life_stage: stage,
      count: counts[stage],
    }));

  function close() {
    router.push({ pathname: "/", query: { week: weekStart } });
  }

  function bump(stage: LifeStage, by: number) {
    setCounts((current) => ({
      ...current,
      [stage]: Math.max(0, Math.min(MAX_PER_STAGE, current[stage] + by)),
    }));
  }

  function addTaste() {
    const value = draft.trim();
    if (!value || dislikes.includes(value)) return setDraft("");
    setDislikes((current) => [...current, value]);
    setDraft("");
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

  const save = () =>
    act(async () => {
      // The invitation is written first: it is the part that has to survive a
      // failed or later-redone generation.
      await apiPost("/invitations", {
        week_start: weekStart,
        day_of_week: dayOfWeek,
        meal_type: mealType,
        guests: guests(),
        dislikes,
      });

      // Then the meal, through the same endpoint the week uses. The tastes ride
      // on every guest group as a soft signal — the party dislikes it, whoever
      // in the party.
      setStartedAt(Date.now());
      await apiPost("/meal-plans", {
        scope: { type: "slot", day: dates[dayOfWeek], meal_type: mealType },
        guests: guests().map((group) => ({
          life_stage: group.life_stage,
          count: group.count,
          excluded_allergens: [],
          dislikes,
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
          <p className="text-xs tracking-[0.06em] text-ink-muted uppercase">{t("kicker")}</p>
          <h2 className="mt-1.5 text-lg leading-[1.2] font-semibold">
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
            {/* Transitory: they never become members, so the household's
                everyday menus are untouched by a dinner that happens once. */}
            <p className="text-sm leading-[1.5] text-ink-muted text-pretty">{t("intro")}</p>

            <Step index={1} heading={t("whenHeading")}>
              {/* Radios sharing a `name` are already a group to a screen
                  reader; an extra `role` here would only add an unnamed one. */}
              <div className="grid grid-cols-7 gap-1.5">
                {DAYS.map((index) => (
                  <Chip
                    key={index}
                    name="invitation-day"
                    checked={dayOfWeek === index}
                    onSelect={() => setDayOfWeek(index)}
                    className="px-0 py-2 text-xs font-semibold"
                  >
                    {/* The initial and the date: seven full weekday names do
                        not fit, and the number is what people actually aim at. */}
                    <span className="block first-letter:uppercase">
                      {format.dateTime(day(index), { weekday: "narrow" })}
                    </span>
                    <span className="block font-normal">
                      {format.dateTime(day(index), { day: "numeric" })}
                    </span>
                  </Chip>
                ))}
              </div>

              <div className="mt-2 grid grid-cols-2 gap-1.5">
                {MEAL_TYPES.map((meal) => (
                  <Chip
                    key={meal}
                    name="invitation-meal"
                    checked={mealType === meal}
                    onSelect={() => setMealType(meal)}
                    className={cx(
                      "flex min-h-11 items-center justify-center text-sm",
                      mealType === meal && "font-medium",
                    )}
                  >
                    {tMeal(meal)}
                  </Chip>
                ))}
              </div>
            </Step>

            <Step index={2} heading={t("guestsCounts")}>
              <ul className="flex flex-col gap-2">
                {LIFE_STAGES.map((stage) => (
                  <li
                    key={stage}
                    className="flex items-center gap-2.5 rounded-card border border-border bg-surface-raised px-3 py-2.5"
                  >
                    <span className="flex-1 text-sm">{tStage(stage)}</span>
                    <Button
                      size="sm"
                      className="size-9 px-0 text-base"
                      disabled={busy || counts[stage] === 0}
                      aria-label={t("fewerGuests", { stage: tStage(stage) })}
                      onClick={() => bump(stage, -1)}
                    >
                      −
                    </Button>
                    {/* Announced on change, so the count is not a number only
                        a sighted user can check after pressing the button. */}
                    <output
                      aria-live="polite"
                      className={cx(
                        "w-6 text-center text-[15px] font-semibold",
                        counts[stage] === 0 && "text-ink-muted",
                      )}
                    >
                      {counts[stage]}
                    </output>
                    <Button
                      size="sm"
                      className="size-9 px-0 text-base"
                      disabled={busy || counts[stage] >= MAX_PER_STAGE}
                      aria-label={t("moreGuests", { stage: tStage(stage) })}
                      onClick={() => bump(stage, 1)}
                    >
                      +
                    </Button>
                  </li>
                ))}
              </ul>
              <p className="mt-2.5 text-[13px] leading-[1.45] text-ink-body text-pretty">
                {t("stageMatters")}
              </p>
            </Step>

            <Step index={3} heading={t("tastesHeading")} aside={t("optional")}>
              {/* Chips rather than one comma-separated line: a field you have
                  to re-read to know what is in it is a field you get wrong. */}
              {dislikes.length > 0 && (
                <ul className="mb-2.5 flex flex-wrap gap-1.5">
                  {dislikes.map((taste) => (
                    <li
                      key={taste}
                      className="flex items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-sm text-ink"
                    >
                      <span>{taste}</span>
                      <button
                        type="button"
                        onClick={() =>
                          setDislikes((current) => current.filter((item) => item !== taste))
                        }
                        aria-label={t("dropTaste", { label: taste })}
                        className="text-ink-faint hover:text-danger"
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <div className="flex gap-2">
                <input
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  // Enter adds a taste; it must not submit anything, because
                  // saving is what asks the model for a meal.
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addTaste();
                    }
                  }}
                  placeholder={t("tastesPlaceholder")}
                  aria-label={t("tastesHeading")}
                  className={cx(
                    "h-10 min-w-0 flex-1 rounded-control border border-border bg-surface-raised px-3 text-sm",
                    "text-ink placeholder:text-ink-faint focus:border-border-strong",
                    "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
                  )}
                />
                <Button disabled={busy || !draft.trim()} onClick={addTaste}>
                  {t("tastesAdd")}
                </Button>
              </div>

              <p className="mt-2.5 text-[13px] leading-[1.45] text-ink-body text-pretty">
                {t("tastesHint")}
              </p>
            </Step>

            {/* The one thing this form deliberately cannot do. No allergen
                field: nobody can answer that on a guest's behalf, and a field
                that looks like a filter would be read as one. */}
            <p className="rounded-control border border-danger/30 bg-danger-soft px-3 py-2.5 text-[13px] leading-[1.45] text-danger text-pretty">
              {t("noGuarantee")}
            </p>

            {error && <p className="text-sm text-danger">{error}</p>}
          </>
        )}
      </div>

      {startedAt === null && (
        <div className="flex flex-col gap-2.5 border-t border-border px-5 py-4">
          <Button
            variant="primary"
            className="w-full"
            disabled={busy || total === 0}
            onClick={save}
          >
            {t("save")}
          </Button>
          <p className="text-[13px] leading-[1.45] text-ink-body text-pretty">{t("saveHint")}</p>

          {editing && (
            <>
              <Button
                variant="danger"
                className="mt-2 w-full"
                disabled={busy}
                onClick={remove}
              >
                {t("remove")}
              </Button>
              <p className="text-[13px] leading-[1.45] text-ink-body text-pretty">
                {t("removeHint")}
              </p>
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}
