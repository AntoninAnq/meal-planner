import { getTranslations } from "next-intl/server";

import { DishCard } from "@/components/plan/DishCard";
import { Link } from "@/i18n/navigation";
import { cx } from "@/lib/cx";
import type { MealType, PlanSlot, Violation } from "@/lib/api/types";
import { hasDivergence } from "@/lib/plan";

/**
 * Adaptive: the simple case must look simple.
 *
 * One dish everyone eats renders as the dish, undecorated. Eater badges and
 * variants appear only where the household diverges — otherwise a perfectly
 * ordinary week turns into a wall of names.
 */
export async function SlotCard({
  mealType,
  slot,
  memberNames,
  violations,
  href,
  className,
}: {
  mealType: MealType;
  slot: PlanSlot | undefined;
  memberNames: Record<string, string>;
  violations: Violation[];
  /** Opens the slot panel. The panel is driven by the URL, so the back button
   * closes it and a reload reopens it on the same slot. */
  href: { pathname: "/"; query: Record<string, string> };
  className?: string;
}) {
  const t = await getTranslations("plan");
  const tMeal = await getTranslations("mealType");

  const dishes = slot?.dishes ?? [];
  const diverges = hasDivergence(dishes);
  const broken = violations.length > 0;

  return (
    <Link
      href={href}
      className={cx(
        "flex flex-col gap-1.5 rounded-card border bg-surface-raised px-3 py-2.5",
        "transition-colors hover:border-border-strong",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        broken ? "border-danger/50 bg-danger-soft/40" : "border-border",
        className,
      )}
    >
      <p className="text-xs font-medium tracking-wide text-ink-faint uppercase">
        {tMeal(mealType)}
      </p>

      {dishes.length === 0 ? (
        <p className="text-sm text-ink-faint">{t("emptySlot")}</p>
      ) : (
        <div className={cx("flex flex-col", diverges ? "gap-2" : "gap-0")}>
          {dishes.map((dish) => (
            <DishCard
              key={dish.id}
              dish={dish}
              memberNames={memberNames}
              showEaters={diverges}
            />
          ))}
        </div>
      )}

      {/* The codes stay in the logs. What is shown is that this meal is the one
          to redo — the only reaction a violation actually allows. */}
      {broken && <p className="text-xs font-medium text-danger">{t("slotIncomplete")}</p>}
    </Link>
  );
}
