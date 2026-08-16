import { getTranslations, setRequestLocale } from "next-intl/server";

import { SettingsForm } from "@/components/settings/SettingsForm";
import { Link, redirect } from "@/i18n/navigation";
import { apiGet } from "@/lib/api/server";
import type {
  DietaryConstraint,
  Household,
  HouseholdSettings,
  MealSlot,
  Member,
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

  const [settings, members, constraints, slots] = await Promise.all([
    apiGet<HouseholdSettings>("/household/settings"),
    apiGet<Member[]>("/members"),
    apiGet<DietaryConstraint[]>("/household/constraints"),
    apiGet<MealSlot[]>("/household/slots"),
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
    </main>
  );
}
