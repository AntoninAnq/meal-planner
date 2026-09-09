import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { ReportQueue } from "@/components/admin/ReportQueue";
import { TypeQueue } from "@/components/admin/TypeQueue";
import { Link } from "@/i18n/navigation";
import { apiGet } from "@/lib/api/server";
import type { Operator, RecipeToType, ReportedRecipe } from "@/lib/api/types";

/**
 * The back office — one screen, for the judgement no rule reaches.
 *
 * `db/dish_types.yaml` maps a source rubric to a meal moment, and some rubrics
 * cannot be mapped at all: `Tartes, Clafoutis` holds an onion tart and a
 * strawberry one. Those recipes stay untyped, and an untyped recipe passes the
 * pre-filter — which is how a dessert tart came to be offered as an alternative
 * for a Thursday dinner. A person reading the ingredients settles it instantly.
 *
 * **The guard is the API's, not this page's.** `/admin/*` answers 404 to anyone
 * who is not an operator, so `apiGet` returns null and this renders the same
 * not-found as a mistyped URL. Nothing here decides who may enter — a check
 * written twice is a check that will disagree with itself, and the copy that
 * matters is the one in front of the data.
 */
const NAV =
  "rounded-control border border-border px-3 py-1.5 text-sm text-ink-muted transition-colors " +
  "hover:bg-surface-sunken hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 " +
  "focus-visible:outline-accent";

export default async function AdminPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const [queue, reported, me] = await Promise.all([
    apiGet<RecipeToType[]>("/admin/recipes/untyped"),
    apiGet<ReportedRecipe[]>("/admin/reports"),
    apiGet<Operator>("/admin/me"),
  ]);
  if (queue === null) notFound();

  const t = await getTranslations("admin");

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-5 py-10">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{t("heading")}</h1>
          <p className="mt-1.5 text-sm leading-[1.5] text-ink-muted text-pretty">{t("intro")}</p>
        </div>
        {/* Named, not a bare arrow. The back office is a different place from
            the application, reached by typing a URL, and an operator classifying
            recipes for twenty minutes needs a way out that reads as one. */}
        <nav className="flex flex-none gap-2">
          {/* Households are owner-only, reads included. Showing the link to a
              contributor would offer a door that answers not-found. */}
          {me?.level === "owner" && (
            <Link href="/admin/households" className={NAV}>
              {t("households")}
            </Link>
          )}
          <Link href="/admin/operators" className={NAV}>
            {t("operators")}
          </Link>
          <Link href="/" className={NAV}>
            ← {t("back")}
          </Link>
        </nav>
      </header>

      {/* Reports first: somebody complained, and their week is already wrong.
          Classifying is the steady work, and it waits. */}
      {reported !== null && reported.length > 0 && (
        <section className="flex flex-col gap-3 rounded-card border border-border bg-surface-sunken px-4 py-4">
          <div>
            <h2 className="font-semibold">{t("reportsHeading")}</h2>
            <p className="mt-1 text-sm leading-[1.5] text-ink-muted text-pretty">
              {t("reportsIntro")}
            </p>
          </div>
          <ReportQueue initial={reported} />
        </section>
      )}

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="font-semibold">{t("queueHeading")}</h2>
          {/* Moved down from the page heading, which now names the whole back
              office rather than the one queue that happened to be built first. */}
          <p className="mt-1 text-sm leading-[1.5] text-ink-muted text-pretty">
            {t("queueIntro")}
          </p>
        </div>
        <TypeQueue initial={queue} />
      </section>
    </main>
  );
}
