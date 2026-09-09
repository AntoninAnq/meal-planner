import { getTranslations, setRequestLocale } from "next-intl/server";

import { SettingsForm } from "@/components/settings/SettingsForm";
import { SignOutButton } from "@/components/SignOutButton";
import { Link, redirect } from "@/i18n/navigation";
import { apiGet } from "@/lib/api/server";
import type {
  DietaryConstraint,
  Household,
  HouseholdSettings,
  MealSlot,
  Member,
  Operator,
} from "@/lib/api/types";

/** Screen 6. Everything the onboarding deliberately did not ask. */
export default async function SettingsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("settings");

  const household = await apiGet<Household>("/household");
  if (household === null) return redirect({ href: "/", locale });

  const [settings, members, constraints, slots, operator] = await Promise.all([
    apiGet<HouseholdSettings>("/household/settings"),
    apiGet<Member[]>("/members"),
    apiGet<DietaryConstraint[]>("/household/constraints"),
    apiGet<MealSlot[]>("/household/slots"),
    // Null for almost everyone: `/admin/*` answers 404 to anyone who is not an
    // operator, so the absence of the link and the absence of the page say the
    // same thing.
    apiGet<Operator>("/admin/me"),
  ]);

  if (!settings?.onboarded_at) return redirect({ href: "/onboarding", locale });

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-8 px-5 py-10">
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t("heading")}</h1>
        <Link href="/" className="text-sm text-ink-muted hover:text-ink">
          {t("backToWeek")}
        </Link>
      </header>

      <SettingsForm
        household={household}
        settings={settings}
        members={members ?? []}
        constraints={constraints ?? []}
        slots={slots ?? []}
      />

      {/* Here rather than in the week's navigation, which is about WHICH week
          you are looking at — the same reason the invitation left that bar.
          This screen is where the things about you and this instance live. */}
      {operator && (
        <section className="border-t border-border pt-6">
          <h2 className="text-sm font-medium">{t("operatorHeading")}</h2>
          <p className="mt-1 text-sm text-ink-muted text-pretty">{t("operatorHint")}</p>
          <Link
            href="/admin"
            className="mt-2.5 inline-flex h-10 items-center justify-center rounded-control border border-border bg-surface-raised px-4 text-sm font-medium text-ink transition-colors hover:bg-surface-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {t("operatorLink")}
          </Link>
        </section>
      )}

      {/* The one thing that makes a bug report actionable. Nothing else here
          identifies a household to the operator: no email is stored, and the
          household name is neither unique nor stable. Shown rather than asked
          for — the alternative was to start keeping an address. */}
      <section className="border-t border-border pt-6">
        <h2 className="text-sm font-medium">{t("supportHeading")}</h2>
        <p className="mt-1 text-sm text-ink-muted text-pretty">{t("supportHint")}</p>
        <p className="mt-2.5 font-mono text-lg font-semibold tracking-[0.08em] select-all">
          {household.support_code}
        </p>
      </section>

      {/* Last, and set apart. Signing out is where every product puts it, and
          putting it in the week's navigation instead would sit it between
          "previous week" and "next week" — one misplaced tap from a household
          that meant to look at Thursday. */}
      <div className="flex justify-start border-t border-border pt-6">
        <SignOutButton />
      </div>
    </main>
  );
}
