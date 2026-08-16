import { getTranslations, setRequestLocale } from "next-intl/server";

import { OnboardingFlow } from "@/components/onboarding/OnboardingFlow";
import { redirect } from "@/i18n/navigation";
import { apiGet } from "@/lib/api/server";
import type { DietaryConstraint, Household, HouseholdSettings, Member } from "@/lib/api/types";

/**
 * Screen 2. Reads on the server, writes from the browser.
 *
 * Reached by redirection from `/` when `onboarded_at` is null, and left the
 * same way once it is stamped — so the two screens can never disagree about
 * whether the household is set up.
 */
export default async function OnboardingPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("onboarding");

  const household = await apiGet<Household>("/household");
  if (household === null) redirect({ href: "/", locale });

  const settings = await apiGet<HouseholdSettings>("/household/settings");
  // Already done: this page has nothing to add, and re-running it would let
  // someone add a second set of members by using the back button.
  if (settings?.onboarded_at) redirect({ href: "/", locale });

  const members = (await apiGet<Member[]>("/members")) ?? [];
  const constraints = (await apiGet<DietaryConstraint[]>("/household/constraints")) ?? [];

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-8 px-5 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">{t("heading")}</h1>
        <p className="text-ink-muted">{t("intro")}</p>
      </header>

      <OnboardingFlow initialMembers={members} initialConstraints={constraints} />
    </main>
  );
}
