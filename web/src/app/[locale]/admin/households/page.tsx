import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { Households } from "@/components/admin/Households";
import { Link } from "@/i18n/navigation";
import { apiGet } from "@/lib/api/server";
import type { AdminHouseholds } from "@/lib/api/types";

/**
 * Who is on the instance, and what to do about one of them.
 *
 * The last of the operator commands to leave the terminal, and the one that
 * most deserved the wait: everything here acts on people rather than on the
 * catalogue. Owner-only down to the read — a helper recruited to classify tarts
 * has no business with the list of families — and enforced by the API, which
 * answers 404, so this page renders the same not-found as a mistyped URL.
 *
 * The list is the busiest households, not all of them. "Who is burning the
 * budget" is why anybody opens this, and a complete list would grow with the
 * instance and be read by nobody; the search box covers the other question,
 * server-side, so the page does not depend on the instance staying small.
 */
export default async function HouseholdsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const data = await apiGet<AdminHouseholds>("/admin/households");
  if (data === null) notFound();

  const t = await getTranslations("households");

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-5 py-10">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{t("heading")}</h1>
          <p className="mt-1.5 text-sm leading-[1.5] text-ink-muted text-pretty">{t("intro")}</p>
        </div>
        <Link
          href="/admin"
          className="flex-none rounded-control border border-border px-3 py-1.5 text-sm text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← {t("backToQueue")}
        </Link>
      </header>

      <Households initial={data} />
    </main>
  );
}
