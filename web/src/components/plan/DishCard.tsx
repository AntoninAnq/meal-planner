import { getTranslations } from "next-intl/server";

import { cx } from "@/lib/cx";
import type { Dish } from "@/lib/api/types";

/**
 * What a card may claim, and what it still may not.
 *
 * Time and effort are now shown — but only when the SOURCE declared them and
 * the rating was computed from those declarations (§6.4). They are absent on
 * about a fifth of the catalogue, and the card then says nothing: the original
 * refusal stands, which was never "no metadata" but "no INVENTED metadata".
 *
 * Still no explanation of why a dish was chosen. That is a separate call on a
 * single slot when someone asks, not a sentence generated alongside every
 * dish — a plausible justification produced for free teaches people to trust
 * explanations exactly where they are hollow.
 *
 * The one thing the card must never stay silent about is a dish someone typed
 * themselves: no filter looked at it, and unlike everything else here that is
 * permanent (UX §15).
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
  const effort = [
    dish.minutes ? t("minutes", { count: dish.minutes }) : null,
    dish.complexity ? t(`complexity.${dish.complexity}` as "complexity.1") : null,
  ].filter(Boolean);

  return (
    <div className={cx(showEaters && "rounded-control border border-border px-2.5 py-2")}>
      <p className="text-sm leading-snug font-medium text-ink">{dish.label ?? t("untitled")}</p>

      {effort.length > 0 && (
        <p className="mt-0.5 text-xs text-ink-faint">{effort.join(" · ")}</p>
      )}

      {/* Nothing verified this one. The filter reads tags, and a title has
          none — so this mark does not disappear the way the V0 banner did. */}
      {dish.source === "user" && (
        <p className="mt-0.5 text-xs text-ink-muted italic">{t("handWritten")}</p>
      )}

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
