import { getTranslations } from "next-intl/server";

import { ExclusionRestore } from "@/components/plan/ExclusionButton";
import { FavoriteRemove } from "@/components/plan/FavoriteButton";
import type { Exclusion, Favorite } from "@/lib/api/types";

/**
 * The third tab: what the household means to cook again — and, under it, what
 * it never wants proposed again.
 *
 * What this screen deliberately does NOT do is put a favourite into the week.
 * That would need a day-and-meal picker, which is a second path to an action
 * that already has one — in the only place that knows the context: who is
 * eating, what was there before, and which allergen is in the room.
 *
 * Allergens are not flagged here either. A favourite is not a planned meal, so
 * the warning belongs to the moment the dish reaches a plate. The risk is
 * accepted and named: a household can keep a favourite somebody cannot eat
 * without seeing it said on this page.
 *
 * The dishes set aside live here because this is where a favourite is looked
 * for: once a withheld dish is off every week, this list is the only way back.
 *
 * Sorted by when it was added, most recent first. No search and no filter
 * while the list is short; past thirty or so, both this and the sort need
 * revisiting.
 */
export async function FavoritesView({
  favorites,
  exclusions,
}: {
  favorites: Favorite[];
  exclusions: Exclusion[];
}) {
  const t = await getTranslations("favorites");
  const tPlan = await getTranslations("plan");
  const tExclusions = await getTranslations("exclusions");

  const saved =
    favorites.length === 0 ? (
      // Written out rather than `ui/EmptyState`: that primitive draws a dashed
      // border and puts its two lines on one type size, and this state carries
      // three registers — the state, what to do about it, and the rule that
      // explains an absence elsewhere in the product.
      <div className="flex flex-col items-center gap-4 rounded-card border border-border bg-surface-raised px-9 py-11 text-center">
        <p className="text-[17px] font-semibold text-ink">{t("emptyTitle")}</p>
        <p className="max-w-[52ch] text-sm leading-[1.6] text-ink-body">{t("emptyBody")}</p>
        {/* The one place in the product where I7 is explained to the person
            using it. It is what makes the absence of a control on a
            model-proposed dish legible; without it that absence reads as a
            bug, and the sentence has nowhere else to live. */}
        <p className="max-w-[56ch] text-[13px] leading-[1.6] text-ink-muted">{t("emptyRule")}</p>
      </div>
    ) : (
      <section>
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="text-[22px] font-semibold text-ink">{t("heading")}</h2>
          <p className="text-sm text-ink-muted">{t("count", { count: favorites.length })}</p>
        </div>

        <p className="mt-2 max-w-[70ch] text-sm leading-[1.55] text-ink-body">{t("help")}</p>

        <ul className="mt-[22px] overflow-hidden rounded-card border border-border bg-surface-raised">
          {favorites.map((favorite) => {
            const effort = [
              favorite.minutes ? tPlan("minutes", { count: favorite.minutes }) : null,
              favorite.complexity
                ? tPlan(`complexity.${favorite.complexity}` as "complexity.1")
                : null,
            ].filter(Boolean);

            return (
              <li
                key={favorite.recipe_id}
                className="flex items-center gap-5 border-b border-border px-[18px] py-[15px] last:border-b-0"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-[15px] font-semibold text-ink [overflow-wrap:anywhere]">
                    {favorite.title}
                  </p>
                  {/* Silent on the fifth of the catalogue that declares neither a
                      time nor a step count, rather than implying it is quick. */}
                  {effort.length > 0 && (
                    <p className="mt-0.5 text-[13px] text-ink-muted">{effort.join(" · ")}</p>
                  )}
                </div>

                {/* The other half of I9: we keep the facts and send people to the
                    author for the recipe itself. */}
                {favorite.source_url && (
                  <a
                    href={favorite.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    aria-label={tPlan("sourceLinkLabel", { title: favorite.title })}
                    className="flex-none text-[13px] text-ink-body underline underline-offset-4 hover:text-accent-hover"
                  >
                    {tPlan("sourceLink")} ↗
                  </a>
                )}

                <FavoriteRemove recipeId={favorite.recipe_id} title={favorite.title} />
              </li>
            );
          })}
        </ul>
      </section>
    );

  return (
    <div className="flex flex-col gap-10">
      {saved}

      {/* Only when there is something: most households never set a dish aside,
          and an empty section would be one more thing to read for nothing. */}
      {exclusions.length > 0 && (
        <section>
          <h2 className="text-[17px] font-semibold text-ink">{tExclusions("heading")}</h2>
          <p className="mt-1 max-w-[70ch] text-sm leading-[1.55] text-ink-body">
            {tExclusions("help")}
          </p>

          <ul className="mt-4 overflow-hidden rounded-card border border-border bg-surface-raised">
            {exclusions.map((exclusion) => (
              <li
                key={exclusion.recipe_id}
                className="flex items-center gap-5 border-b border-border px-[18px] py-[13px] last:border-b-0"
              >
                <p className="min-w-0 flex-1 text-[15px] text-ink [overflow-wrap:anywhere]">
                  {exclusion.title}
                </p>

                {/* Worth reading again before bringing it back. */}
                {exclusion.source_url && (
                  <a
                    href={exclusion.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    aria-label={tPlan("sourceLinkLabel", { title: exclusion.title })}
                    className="flex-none text-[13px] text-ink-body underline underline-offset-4 hover:text-accent-hover"
                  >
                    {tPlan("sourceLink")} ↗
                  </a>
                )}

                <ExclusionRestore recipeId={exclusion.recipe_id} title={exclusion.title} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
