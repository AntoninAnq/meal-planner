import { getTranslations } from "next-intl/server";

import { cx } from "@/lib/cx";
import type { Dish } from "@/lib/api/types";

/**
 * Deliberately poor, and two refusals go with it.
 *
 * No explanation: the pre-filter is stubbed, so there is no discarded
 * candidate and no applied constraint — the model would produce a plausible,
 * invented justification. The problem is not the inaccuracy, it is what it
 * teaches: trusting explanations exactly when they are hollow.
 *
 * No invented metadata either. Preparation time, difficulty and ingredient
 * counts can all be produced from a title and will be wrong half the time.
 * A poor card beats a card that lies.
 */
export async function DishCard({
  dish,
  memberNames,
  showEaters,
}: {
  dish: Dish;
  memberNames: Record<string, string>;
  showEaters: boolean;
}) {
  const t = await getTranslations("plan");
  const variants = dish.eaters.filter((eater) => eater.serving_variant !== null);

  return (
    <div className={cx(showEaters && "rounded-control border border-border px-2.5 py-2")}>
      <p className="text-sm leading-snug font-medium text-ink">{dish.label ?? t("untitled")}</p>

      {showEaters && dish.eaters.length > 0 && (
        <p className="mt-1 flex flex-wrap gap-1">
          {dish.eaters.map((eater) => (
            <span
              key={eater.member_id}
              className="rounded-full bg-surface-sunken px-2 py-0.5 text-xs text-ink-muted"
            >
              {memberNames[eater.member_id] ?? "?"}
            </span>
          ))}
        </p>
      )}

      {/* The serving variant is the product's best possible outcome: one
          preparation, a different plate. It has to be legible, or nobody knows
          to set the portion aside before salting. */}
      {variants.map((eater) => (
        <p key={eater.member_id} className="mt-1 text-xs text-accent">
          {t("variant", {
            name: memberNames[eater.member_id] ?? "?",
            variant: eater.serving_variant ?? "",
          })}
        </p>
      ))}
    </div>
  );
}
