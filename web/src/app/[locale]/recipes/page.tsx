import { getTranslations, setRequestLocale } from "next-intl/server";

import { RecipeWorkshop } from "@/components/recipes/RecipeWorkshop";
import { Link, redirect } from "@/i18n/navigation";
import { apiGet } from "@/lib/api/server";
import type { Household, HouseholdRecipe } from "@/lib/api/types";

/**
 * Where a household writes the dishes the catalogue does not carry.
 *
 * Its own page rather than a panel inside the week: writing a recipe is not a
 * decision about Tuesday, and the place it belongs to is beside the favourites
 * — what this household keeps, whoever wrote it.
 */
export default async function RecipesPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("recipes");

  const household = await apiGet<Household>("/household");
  if (household === null) return redirect({ href: "/", locale });

  const recipes = await apiGet<HouseholdRecipe[]>("/recipes");

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-7 px-5 py-10">
      <header className="flex flex-col gap-2">
        <Link href="/" className="text-sm text-ink-muted hover:text-ink">
          ← {t("back")}
        </Link>
        <h1 className="text-2xl font-semibold text-ink">{t("heading")}</h1>
        <p className="max-w-[70ch] text-sm leading-[1.55] text-ink-body">{t("intro")}</p>
      </header>

      <RecipeWorkshop recipes={recipes ?? []} />
    </main>
  );
}
