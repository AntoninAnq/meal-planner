import { getTranslations } from "next-intl/server";

import { VariantConfirm } from "@/components/plan/VariantConfirm";
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
 *
 * The link back to the source is the other half of I9: we keep the facts —
 * ingredients, timings, rubric — and send people to the author for the recipe
 * itself. It is not decoration; without it the catalogue takes and gives
 * nothing back.
 */
export async function DishCard({
  dish,
  memberNames,
  multiple,
  showEaters,
  planId,
}: {
  dish: Dish;
  memberNames: Record<string, string>;
  /** True only when the slot holds SEVERAL dishes — then, and only then, does a
   * card need a box around it and the names of who eats it. A single dish with
   * a serving variant is not that case: the variant line already names the one
   * person it concerns, and listing the other three underneath is the wall of
   * names the grid used to be (UX §5). */
  multiple: boolean;
  /** Names of who eats this dish, shown only where there is divergence to show.
   * The slot decides: the dish the largest group eats is the default one, and
   * naming its eaters restated the household on every card of the week — the
   * wall of names UX §5 asks us to drop. A dish only some of the household eats
   * is the exception, and the exception is what has to be named. */
  showEaters: boolean;
  /** Null when there is no plan to act on — the empty-week placeholder. The
   * confirmation button needs it and nothing else on this card does. */
  planId?: string | null;
}) {
  const t = await getTranslations("plan");
  const variants = dish.eaters.filter((eater) => eater.serving_variant !== null);
  const effort = [
    dish.minutes ? t("minutes", { count: dish.minutes }) : null,
    dish.complexity ? t(`complexity.${dish.complexity}` as "complexity.1") : null,
  ].filter(Boolean);

  return (
    <div className={cx("min-w-0", multiple && "rounded-control border border-border px-2.5 py-2")}>
      {/* `anywhere` rather than a truncation: "Aubergines farcies de viande et
          feta à la méditerranéenne" ran out of its card, and the name of the
          dish IS the information the card carries — an ellipsis would cut the
          one thing worth reading. */}
      <p className="text-sm leading-[1.3] font-semibold text-ink text-pretty [overflow-wrap:anywhere]">
        {dish.label ?? t("untitled")}
      </p>

      {(effort.length > 0 || dish.source_url) && (
        // `ink-muted`, not `ink-faint`: this line was one of the greys doing
        // the work of size, and it sat under 4.5:1 at this body size.
        <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11.5px] text-ink-muted">
          {effort.length > 0 && <span>{effort.join(" · ")}</span>}

          {/* `pointer-events-auto` is load-bearing: the whole slot card is a
              link to the panel, so its contents are made inert and this one
              element opts back in. The card link itself is an overlay behind
              this, which is what keeps an anchor from nesting in an anchor —
              invalid HTML that browsers repair by dropping one of them. */}
          {dish.source_url && (
            <a
              href={dish.source_url}
              target="_blank"
              rel="noreferrer noopener"
              aria-label={t("sourceLinkLabel", { title: dish.label ?? t("untitled") })}
              className={cx(
                "pointer-events-auto relative z-10 rounded-full bg-surface-sunken px-1.5 py-0.5",
                "text-ink-muted transition-colors hover:bg-accent-soft hover:text-accent",
                "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
              )}
            >
              {t("sourceLink")} ↗
            </a>
          )}
        </p>
      )}

      {/* Nothing verified this one. The filter reads tags, and a title has
          none — so this mark does not disappear the way the V0 banner did. */}
      {dish.source === "user" && (
        <p className="mt-0.5 text-xs text-ink-muted italic">{t("handWritten")}</p>
      )}

      {/* The wedge, made visible: two meals built on the same things is the
          whole argument of the product, and it showed up nowhere.

          It says "the same ingredients" and not "the same base", because that
          is what was measured. The two colombos of a real week share aubergine,
          courgette, lime and bay — and no colombo at all, that line never
          resolved. A shared base is a fact about a saucepan, and saucepans live
          in the preparation steps the catalogue does not keep. */}
      {dish.shares_ingredients_with && (
        <p className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2 py-[3px]">
          <span aria-hidden className="h-[5px] w-[5px] flex-none rounded-full bg-accent-hover" />
          <span className="text-[11px] leading-none font-semibold text-accent-hover">
            {t("sharedIngredients")}
          </span>
        </p>
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
          to set the portion aside before salting.

          A variant a baby's assignment DEPENDS on is a different thing, and it
          does not get to look like the others. No catalogue recipe suits a
          baby, so nothing vouched for this plate but a model that cannot judge
          texture — §4.9 puts that decision on the parent, and the interface
          has to make the difference visible or the confirmation is theatre. */}
      {variants.map((eater) => {
        const name = memberNames[eater.member_id] ?? "?";
        const pending = eater.requires_confirmation && !eater.variant_confirmed_at;

        return (
          <div key={eater.member_id} className="mt-[7px]">
            <p className={cx("text-xs leading-[1.35]", pending ? "text-ink" : "text-accent")}>
              {t("variant", { name, variant: eater.serving_variant ?? "" })}
            </p>

            {eater.removals.length > 0 && (
              <p className="text-xs text-ink-muted">
                {t("variantRemovals", { items: eater.removals.join(", ") })}
              </p>
            )}

            {/* The button says "to confirm" and that is the whole message. It
                used to be followed by a sentence saying the same thing again,
                which made the state look like a warning rather than a thing to
                click. */}
            {eater.requires_confirmation && planId && (
              <p className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <VariantConfirm
                  planId={planId}
                  dishId={dish.id}
                  memberId={eater.member_id}
                  name={name}
                  variant={eater.serving_variant}
                  confirmed={eater.variant_confirmed_at !== null}
                />
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
