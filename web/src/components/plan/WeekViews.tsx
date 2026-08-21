import { getFormatter, getTranslations } from "next-intl/server";

import { SlotCard } from "@/components/plan/SlotCard";
import { cx } from "@/lib/cx";
import type { MealSlot, MealType, PlanSlot, Violation } from "@/lib/api/types";
import { slotKey, type SlotKey } from "@/lib/plan";
import { weekDates } from "@/lib/week";

/**
 * Two views of the same object, not one view at two sizes.
 *
 * The grid answers "how does my week look"; the list answers "what am I doing
 * now". Deriving one from the other with media queries gives you both, worse.
 * Both trees are rendered and the CSS in globals.css decides which is visible —
 * which is what makes the first paint correct with no JavaScript at all.
 */
export type WeekViewProps = {
  weekStart: string;
  today: string;
  enabledSlots: MealSlot[];
  slots: Map<SlotKey, PlanSlot>;
  violations: Map<SlotKey | "", Violation[]>;
  memberNames: Record<string, string>;
  /** Needed only to confirm a baby's serving variant, which is an action on a
   * dish of THIS plan. Null on a week with no plan yet. */
  planId: string | null;
};

function mealsOf(enabledSlots: MealSlot[], dayOfWeek: number): MealType[] {
  return enabledSlots
    .filter((slot) => slot.day_of_week === dayOfWeek && slot.enabled)
    .map((slot) => slot.meal_type);
}

export async function WeekGrid(props: WeekViewProps) {
  const format = await getFormatter();
  const t = await getTranslations("plan");
  const dates = weekDates(props.weekStart);

  return (
    <div className="grid grid-cols-7 gap-2">
      {dates.map((date, dayOfWeek) => {
        const meals = mealsOf(props.enabledSlots, dayOfWeek);
        const isToday = date === props.today;

        return (
          <div key={date} className="flex min-w-0 flex-col gap-2">
            <div
              className={cx(
                "px-1 text-sm",
                isToday ? "font-semibold text-accent" : "text-ink-muted",
              )}
            >
              <span className="capitalize">
                {format.dateTime(new Date(`${date}T12:00:00Z`), { weekday: "short" })}
              </span>{" "}
              <span className="text-ink-faint">
                {format.dateTime(new Date(`${date}T12:00:00Z`), { day: "numeric" })}
              </span>
            </div>

            {meals.length === 0 ? (
              <p className="px-1 text-xs text-ink-faint">{t("noSlot")}</p>
            ) : (
              meals.map((mealType) => {
                const key = slotKey(dayOfWeek, mealType);
                return (
                  <SlotCard
                    key={key}
                    mealType={mealType}
                    slot={props.slots.get(key)}
                    memberNames={props.memberNames}
                    violations={props.violations.get(key) ?? []}
                    planId={props.planId}
                    href={{ pathname: "/", query: { week: props.weekStart, slot: key } }}
                  />
                );
              })
            )}
          </div>
        );
      })}
    </div>
  );
}

export async function DayList(props: WeekViewProps) {
  const format = await getFormatter();
  const t = await getTranslations("plan");
  const dates = weekDates(props.weekStart);

  return (
    <div className="flex flex-col gap-5">
      {dates.map((date, dayOfWeek) => {
        const meals = mealsOf(props.enabledSlots, dayOfWeek);
        if (meals.length === 0) return null;

        const isToday = date === props.today;
        const isPast = date < props.today;

        return (
          <section key={date} className={cx("flex flex-col gap-2", isPast && "opacity-55")}>
            <h3
              className={cx(
                "text-sm capitalize",
                isToday ? "font-semibold text-accent" : "text-ink-muted",
              )}
            >
              {isToday
                ? t("today")
                : format.dateTime(new Date(`${date}T12:00:00Z`), {
                    weekday: "long",
                    day: "numeric",
                    month: "long",
                  })}
            </h3>

            {meals.map((mealType) => {
              const key = slotKey(dayOfWeek, mealType);
              return (
                <SlotCard
                  key={key}
                  mealType={mealType}
                  slot={props.slots.get(key)}
                  memberNames={props.memberNames}
                  violations={props.violations.get(key) ?? []}
                  planId={props.planId}
                  href={{ pathname: "/", query: { week: props.weekStart, slot: key } }}
                />
              );
            })}
          </section>
        );
      })}
    </div>
  );
}
