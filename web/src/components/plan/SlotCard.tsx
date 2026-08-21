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
 *
 * **The card is not an anchor, it CONTAINS one.** It used to be a `<Link>`
 * wrapping everything, which made the source link inside a dish an anchor
 * nested in an anchor: invalid HTML that browsers silently repair by dropping
 * one of the two, so either the panel or the recipe stopped opening depending
 * on the engine. The link is now an overlay stretched over the card, the
 * content sits above it and is inert, and anything that must stay clickable
 * says so itself. Keyboard order is unchanged: the overlay comes first in the
 * DOM, so Tab reaches the slot before the links inside it.
 */
export async function SlotCard({
  mealType,
  slot,
  memberNames,
  violations,
  planId,
  href,
  className,
}: {
  mealType: MealType;
  slot: PlanSlot | undefined;
  memberNames: Record<string, string>;
  violations: Violation[];
  planId: string | null;
  /** Opens the slot panel. The panel is driven by the URL, so the back button
   * closes it and a reload reopens it on the same slot. */
  href: { pathname: "/"; query: Record<string, string> };
  className?: string;
}) {
  const t = await getTranslations("plan");
  const tMeal = await getTranslations("mealType");

  const dishes = slot?.dishes ?? [];
  const guestCount = (slot?.guests ?? []).reduce((total, group) => total + group.count, 0);
  const diverges = hasDivergence(dishes);
  const broken = violations.length > 0;

  return (
    <div
      className={cx(
        "relative rounded-card border bg-surface-raised px-3 py-2.5",
        "transition-colors hover:border-border-strong",
        broken ? "border-danger/50 bg-danger-soft/40" : "border-border",
        className,
      )}
    >
      {/* The focus ring lives on the overlay, not on the container: with
          `focus-within` on the parent, tabbing to a source link inside a dish
          lit up the whole slot as well as the link, and two rings at once say
          nothing about where you are. */}
      <Link
        href={href}
        className={cx(
          "absolute inset-0 rounded-card",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        )}
      >
        <span className="sr-only">{tMeal(mealType)}</span>
      </Link>

      {/* Inert as a block, so a click anywhere lands on the overlay behind it.
          Individual elements opt back in with `pointer-events-auto`. */}
      <div className="pointer-events-none relative flex flex-col gap-1.5">
        <p className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-ink-faint uppercase">
          {tMeal(mealType)}
          {/* Guests are never stored as members, so without this a dinner cooked
              for nine shows up as a dinner for three and nobody remembers why. */}
          {guestCount > 0 && (
            <span className="rounded-full bg-accent-soft px-1.5 py-0.5 text-[0.65rem] normal-case text-accent">
              {t("guests", { count: guestCount })}
            </span>
          )}
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
                planId={planId}
              />
            ))}
          </div>
        )}

        {/* The codes stay in the logs. What is shown is that this meal is the
            one to redo — the only reaction a violation actually allows. */}
        {broken && <p className="text-xs font-medium text-danger">{t("slotIncomplete")}</p>}
      </div>
    </div>
  );
}
