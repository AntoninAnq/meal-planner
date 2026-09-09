import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { Operators } from "@/components/admin/Operators";
import { Link } from "@/i18n/navigation";
import { apiGet } from "@/lib/api/server";
import type { Operator } from "@/lib/api/types";

/**
 * Who may operate the instance — the last thing that still needed a terminal.
 *
 * The endpoints have existed since the gate was built and nothing called them:
 * granting the back office to somebody meant `python -m app.admin operators
 * --grant`, which is a shell on the production host for what is now the most
 * ordinary act of running this thing — accepting help with the retagging.
 *
 * The FIRST owner still cannot be created here, and never will be: the screen
 * that grants operators is itself behind the gate it opens.
 *
 * Its own page rather than a section of `/admin`. The classifying queue is
 * cadenced work — a card, a digit, the next card — and a list of people with
 * a form in it is exactly the kind of thing that breaks a cadence.
 */
export default async function OperatorsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const [operators, me] = await Promise.all([
    apiGet<Operator[]>("/admin/operators"),
    apiGet<Operator>("/admin/me"),
  ]);
  // Same not-found as a mistyped URL: `/admin/*` answers 404 to anyone who is
  // not an operator, so `apiGet` returns null and nothing here has to decide
  // who may enter. A check written twice is a check that will disagree.
  if (operators === null || me === null) notFound();

  const t = await getTranslations("operators");

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

      <Operators initial={operators} me={me} />
    </main>
  );
}
