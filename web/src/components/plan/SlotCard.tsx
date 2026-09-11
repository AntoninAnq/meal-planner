import { getTranslations } from "next-intl/server";

import { DishCard } from "@/components/plan/DishCard";
import { Link } from "@/i18n/navigation";
import { cx } from "@/lib/cx";
import type { Invitation, MealType, PlanSlot, Violation } from "@/lib/api/types";

/**
 * Adaptive: the simple case must look simple.
 *
 * One dish everyone eats renders as the dish, undecorated. Boxes and eater
 * names appear only where the slot actually holds several dishes; a serving
 * variant shows as its own line, because it concerns one person and says so.
 * The grid used to repeat the four first names, the variant sentence and a
 * "not confirmed yet" line on every single card — a perfectly ordinary week
 * turned into a wall of names (UX §5).
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
  invitation,
  inviteHref,
  showMeal = true,
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
  /** When this meal is an invitation, the invitation IS the slot: it takes the
   * cell, with its own banner and its own way back in. It used to live in three
   * places at once — a link in the bar, a badge on the card and a reminder list
   * at the foot of the page — and was easy to miss in all three. */
  invitation?: Invitation;
  inviteHref?: { pathname: "/"; query: Record<string, string> };
  /** False in the grid, where the row already says Lunch or Dinner. The screen
   * reader is told either way, through the overlay link. */
  showMeal?: boolean;
  className?: string;
}) {
  const t = await getTranslations("plan");
  const tMeal = await getTranslations("mealType");
  const tInv = await getTranslations("invitation");

  const dishes = slot?.dishes ?? [];
  const guestCount = (slot?.guests ?? []).reduce((total, group) => total + group.count, 0);
  const inviteCount = (invitation?.guests ?? []).reduce((total, g) => total + g.count, 0);
  const multiple = dishes.length > 1;
  const broken = violations.length > 0;
  // An unplanned meal has no state, so it gets no box: no border, no ground, no
  // "nothing planned". Lunches were already rendering as bare cells and only
  // some dinners as a bordered card, which made one absence look like two. It
  // stays clickable over its whole surface — that is how a meal gets planned.
  const empty = dishes.length === 0;

  // The dish the largest group eats is the default one, and it is the only card
  // that says nothing about who eats it. A tie means there is no default —
  // two halves of the household eating two things is exactly the divergence
  // worth naming, so both cards name theirs.
  const widest = Math.max(0, ...dishes.map((dish) => dish.eaters.length));
  const defaultDish =
    dishes.filter((dish) => dish.eaters.length === widest).length === 1
      ? dishes.find((dish) => dish.eaters.length === widest)
      : undefined;

  const body = (
    <>
      {/* Inert as a block, so a click anywhere lands on the overlay behind it.
          Individual elements opt back in with `pointer-events-auto`. */}
      <div className="pointer-events-none relative flex flex-col gap-1.5">
        {showMeal && (
          <p className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.05em] text-ink-muted uppercase">
            {tMeal(mealType)}
            {/* Guests are never stored as members, so without this a dinner
                cooked for nine shows up as a dinner for three and nobody
                remembers why. Not repeated when an invitation already banners
                the count above. */}
            {guestCount > 0 && !invitation && (
              <span className="rounded-full bg-accent-soft px-1.5 py-0.5 text-[0.65rem] font-normal normal-case text-accent">
                {t("guests", { count: guestCount })}
              </span>
            )}
          </p>
        )}

        {!empty && (
          <div className={cx("flex flex-col", multiple ? "gap-2" : "gap-0")}>
            {dishes.map((dish) => (
              <DishCard
                key={dish.id}
                dish={dish}
                memberNames={memberNames}
                multiple={multiple}
                showEaters={multiple && dish.id !== defaultDish?.id}
                planId={planId}
              />
            ))}
          </div>
        )}

        {/* The codes stay in the logs. What is shown is that this meal is the
            one to redo — the only reaction a violation actually allows. */}
        {/* The banner at the top of the week counts these and says they are
            marked in the grid, so one mark per slot is owed — one, and short.
            It used to be a two-line sentence AND a red rule around the cell,
            which said the same thing three times over. */}
        {broken && (
          <p className="inline-flex">
            <span className="rounded-full bg-danger-soft px-[9px] py-[3px] text-[11.5px] leading-[1.4] font-medium text-danger">
              {t("slotIncomplete")}
            </span>
          </p>
        )}
      </div>
    </>
  );

  // The focus ring lives on the overlay, not on the container: with
  // `focus-within` on the parent, tabbing to a source link inside a dish lit up
  // the whole slot as well as the link, and two rings at once say nothing about
  // where you are.
  const overlay = (
    <Link
      href={href}
      className={cx(
        "absolute inset-0 rounded-card",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
      )}
    >
      <span className="sr-only">{tMeal(mealType)}</span>
    </Link>
  );

  if (invitation && inviteHref) {
    return (
      <div
        className={cx(
          "relative flex flex-col overflow-hidden rounded-card border-[1.5px] border-guest bg-guest-soft",
          className,
        )}
      >
        <div className="flex items-center justify-between gap-1.5 bg-guest px-2.5 py-1.5">
          <span className="text-[10.5px] leading-none font-bold tracking-[0.07em] text-accent-ink uppercase">
            {tInv("dayMark")}
          </span>
          <span className="text-[10.5px] leading-none font-semibold whitespace-nowrap text-guest-soft">
            {tInv("atTable", { count: inviteCount })}
          </span>
        </div>

        <div className="relative flex-1 px-[11px] pt-2.5">
          {overlay}
          {body}
          {/* Guests are anonymous by design — a count and a life stage, nothing
              nominative — so what is shown here is what the household typed:
              the soft signal that steered the suggestion. */}
          {invitation.dislikes.length > 0 && (
            <p className="pointer-events-none relative mt-1.5 text-[11.5px] leading-[1.35] font-medium text-guest-strong">
              {invitation.dislikes.join(" · ")}
            </p>
          )}
        </div>

        <div className="relative px-[11px] pt-[9px] pb-2.5">
          <Link
            href={inviteHref}
            className={cx(
              "inline-block rounded-control border border-guest bg-surface-raised px-2.5 py-[7px]",
              "text-[11.5px] leading-none font-semibold text-guest-strong transition-colors",
              "hover:bg-guest-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-guest",
            )}
          >
            {tInv("edit")}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cx(
        "relative rounded-card px-3 py-2.5 transition-colors",
        empty
          ? "min-h-[58px] hover:bg-surface-sunken"
          : "border border-border bg-surface-raised hover:border-border-strong",
        className,
      )}
    >
      {overlay}
      {body}
    </div>
  );
}
