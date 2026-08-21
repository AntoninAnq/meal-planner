import { getTranslations, setRequestLocale } from "next-intl/server";
import { cookies } from "next/headers";

import { WeekBoard } from "@/components/plan/WeekBoard";
import { SlotPanel } from "@/components/plan/SlotPanel";
import { DayList, WeekGrid, type WeekViewProps } from "@/components/plan/WeekViews";
import { Link, redirect } from "@/i18n/navigation";
import { apiGet } from "@/lib/api/server";
import type { Household, HouseholdSettings, MealPlan, MealSlot, Member } from "@/lib/api/types";
import { parseSlotKey, slotKey, slotsByKey, violationsByKey } from "@/lib/plan";
import { addDays, mondayOf, resolveWeek, weekDates } from "@/lib/week";
import { resolveView, VIEW_COOKIE } from "@/lib/week-view";

/** Expected generation time, in seconds. Configuration, never a constant: a
 * week takes around 30 s on the cloud model and 182 s measured on the local
 * 8B, and every wait threshold derives from it. */
const EXPECTED_SECONDS = Number(process.env.GENERATION_EXPECTED_SECONDS ?? 30);

type Search = Promise<Record<string, string | string[] | undefined>>;

export default async function HomePage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Search;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const household = await apiGet<Household>("/household");
  if (household === null) return <SignIn />;

  const settings = await apiGet<HouseholdSettings>("/household/settings");
  // Never derived from "this household has members": someone interrupted after
  // adding them would be sent straight here, and the allergy question — the one
  // thing the onboarding exists to ask — would never be asked.
  if (!settings?.onboarded_at) redirect({ href: "/onboarding", locale });

  return <Week household={household} locale={locale} searchParams={searchParams} />;
}

async function SignIn() {
  const t = await getTranslations("signIn");

  return (
    <main className="mx-auto flex min-h-dvh max-w-xl flex-col justify-center gap-6 px-5 py-10">
      <h1 className="text-3xl font-semibold text-balance">{t("heading")}</h1>
      <p className="text-ink-muted">{t("body")}</p>

      {/* A real browser navigation, not a Next.js route: `/api/*` is proxied
          to FastAPI, which answers with a redirect to Google. `next/link`
          would try to resolve it client-side and never leave the app. */}
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
      <a
        href="/api/auth/login"
        className="inline-flex h-11 items-center justify-center rounded-control bg-accent px-5 font-medium text-accent-ink transition-colors hover:bg-accent-hover"
      >
        {t("button")}
      </a>

      <p className="text-xs text-ink-faint">{t("privacy")}</p>
    </main>
  );
}

async function Week({
  household,
  locale,
  searchParams,
}: {
  household: Household;
  locale: string;
  searchParams: Search;
}) {
  const t = await getTranslations("plan");
  const search = await searchParams;

  const today = new Date().toISOString().slice(0, 10);
  const weekStart = resolveWeek(search.week, today);

  // The view loads the plan itself rather than displaying the response of the
  // generation POST. That is what makes a lost response survivable: the plan
  // was written before the endpoint replied, so a reload recovers it.
  const [plan, members, enabledSlots] = await Promise.all([
    apiGet<MealPlan | null>(`/meal-plans?week_start=${weekStart}`),
    apiGet<Member[]>("/members"),
    apiGet<MealSlot[]>("/household/slots"),
  ]);

  const memberNames = Object.fromEntries(
    (members ?? []).map((member) => [member.id, member.display_name]),
  );

  const viewProps: WeekViewProps = {
    weekStart,
    today,
    enabledSlots: enabledSlots ?? [],
    slots: slotsByKey(plan),
    violations: violationsByKey(plan?.violations ?? []),
    memberNames,
    planId: plan?.id ?? null,
  };

  const view = resolveView((await cookies()).get(VIEW_COOKIE)?.value);

  // The open slot travels in the URL too: the back button closes the panel and
  // a reload reopens it on the same meal. A mistyped key simply leaves it shut.
  const openSlot = parseSlotKey(
    Array.isArray(search.slot) ? (search.slot[0] ?? "") : (search.slot ?? ""),
  );

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-5 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold">{household.name}</h1>
          <p className="text-sm text-ink-muted">
            {(members ?? []).map((member) => member.display_name).join(" · ")}
          </p>
        </div>

        {/* The week travels in the URL, so back, reload and a shared link all
            land on the same one. */}
        <nav className="flex items-center gap-1 text-sm">
          <Link
            href={{ pathname: "/", query: { week: addDays(weekStart, -7) } }}
            className="rounded-control px-2 py-1 text-ink-muted hover:bg-surface-sunken hover:text-ink"
          >
            {t("previousWeek")}
          </Link>
          <Link
            href="/settings"
            className="rounded-control px-2 py-1 text-ink-muted hover:bg-surface-sunken hover:text-ink"
          >
            {t("settings")}
          </Link>
          <Link
            href={{ pathname: "/", query: { week: mondayOf(today) } }}
            className="rounded-control px-2 py-1 text-ink-muted hover:bg-surface-sunken hover:text-ink"
          >
            {t("thisWeek")}
          </Link>
          <Link
            href={{ pathname: "/", query: { week: addDays(weekStart, 7) } }}
            className="rounded-control px-2 py-1 text-ink-muted hover:bg-surface-sunken hover:text-ink"
          >
            {t("nextWeek")}
          </Link>
        </nav>
      </header>

      {(members ?? []).length === 0 && (
        <p className="text-sm text-ink-muted">{t("noMembers")}</p>
      )}

      <WeekBoard
        initialView={view}
        weekStart={weekStart}
        locale={locale}
        hasPlan={plan !== null}
        generatedAt={plan?.generated_at ?? null}
        violations={plan?.violations ?? []}
        expectedMs={EXPECTED_SECONDS * 1000}
        grid={<WeekGrid {...viewProps} />}
        list={<DayList {...viewProps} />}
      />

      {openSlot && (
        <SlotPanel
          open
          planId={plan?.id ?? null}
          weekStart={weekStart}
          date={weekDates(weekStart)[openSlot.dayOfWeek]}
          dayOfWeek={openSlot.dayOfWeek}
          mealType={openSlot.mealType}
          dishes={
            viewProps.slots.get(slotKey(openSlot.dayOfWeek, openSlot.mealType))?.dishes ?? []
          }
          memberNames={memberNames}
          locale={locale}
          expectedMs={EXPECTED_SECONDS * 1000}
        />
      )}
    </main>
  );
}
