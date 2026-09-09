import { getTranslations, setRequestLocale } from "next-intl/server";
import { cookies } from "next/headers";

import { InvitationPanel } from "@/components/plan/InvitationPanel";
import { WeekBoard } from "@/components/plan/WeekBoard";
import { SlotPanel } from "@/components/plan/SlotPanel";
import { DayList, WeekGrid, type WeekViewProps } from "@/components/plan/WeekViews";
import { Link, redirect } from "@/i18n/navigation";
import { apiGet } from "@/lib/api/server";
import { cx } from "@/lib/cx";
import type {
  Household,
  HouseholdSettings,
  Invitation,
  MealPlan,
  MealSlot,
  Member,
} from "@/lib/api/types";
import {
  invitationsByKey,
  parseSlotKey,
  slotKey,
  slotsByKey,
  violationsByKey,
} from "@/lib/plan";
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

/** Every band lines its content up on the same 1152px column, with 64px
 * gutters on the desktop layout and 20px on the narrow one. The bands
 * themselves run full-bleed, because two of them are tinted. */
const BAND = "mx-auto w-full max-w-6xl px-5 lg:px-16";

/** The one way in, twice: once under the promise, once under the closing
 * question. Both are real browser navigations — see the comment at the call
 * site — so the geometry of `ui/Button.tsx` is reproduced here rather than
 * borrowed, since that primitive renders a `<button>`.
 *
 * 48px tall on a touch screen, 44px on a pointer one, full width until there
 * is room beside it. */
const SIGN_IN_BUTTON =
  "inline-flex h-12 w-full flex-none items-center justify-center rounded-control " +
  "px-5 text-[15px] transition-colors focus-visible:outline-2 " +
  "focus-visible:outline-offset-2 focus-visible:outline-accent lg:h-11 lg:w-auto";

/** The entry screen: what the household gets, before it has an account.
 *
 * Six stacked bands rather than a centred column, because the promise is worth
 * more shown than told — the proof card is the argument of the whole product,
 * and someone who leaves without signing in should at least have seen it.
 *
 * No wordmark: the product has no name yet, and a placeholder would have to be
 * unpicked from every screen later. */
async function SignIn() {
  const t = await getTranslations("signIn");
  const tMeal = await getTranslations("mealType");

  return (
    <main>
      {/* 1. The promise, and the proof beside it. No header above: with no
          name to put on the left, a "sign in" link on the right would only
          repeat the button 150px below. */}
      <section>
        <div
          className={`${BAND} grid grid-cols-1 gap-14 pt-10 pb-8 lg:grid-cols-[minmax(0,1fr)_512px] lg:items-start lg:pt-[76px] lg:pb-[76px]`}
        >
          <div className="flex flex-col items-start">
            <p className="text-[11.5px] font-semibold tracking-[0.09em] text-accent uppercase lg:text-xs">
              {t("eyebrow")}
            </p>

            <h1 className="mt-3.5 text-[31px] leading-[1.1] font-bold tracking-[-0.015em] text-pretty lg:mt-[18px] lg:max-w-[16ch] lg:text-[46px] lg:leading-[1.06] lg:tracking-[-0.02em]">
              {t("heading")}
            </h1>

            <p className="mt-4 text-[15.5px] leading-[1.55] text-ink-body text-pretty lg:mt-[22px] lg:max-w-[46ch] lg:text-[17px]">
              {t("body")}
            </p>

            <div className="mt-[26px] flex w-full flex-col lg:mt-8 lg:w-auto lg:flex-row lg:items-center lg:gap-4">
              {/* A real browser navigation, not a Next.js route: `/api/*` is
                  proxied to FastAPI, which answers with a redirect to Google.
                  `next/link` would try to resolve it client-side and never
                  leave the app. */}
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
              <a
                href="/api/auth/login"
                className={`${SIGN_IN_BUTTON} bg-accent font-medium text-accent-ink hover:bg-accent-hover`}
              >
                {t("button")}
              </a>

              {/* Beside the button on a wide screen; on a narrow one the
                  button is what the visitor came for, and nothing shares its
                  line. */}
              <span className="hidden text-[13px] leading-[1.5] text-ink-muted lg:block lg:max-w-[26ch]">
                {t("reassurance")}
              </span>
            </div>

            <p className="mt-3.5 text-[12.5px] leading-[1.6] text-ink-muted lg:mt-[18px] lg:max-w-[46ch]">
              {t("privacy")}
            </p>
          </div>

          <ProofExtract tone="card" t={t} tMeal={tMeal} className="hidden lg:block" />
        </div>
      </section>

      {/* On a narrow screen the proof drops below the fold as its own band:
          the sign-in button stays above it. */}
      <section className="border-t border-border bg-surface-sunken lg:hidden">
        <div className={BAND}>
          <ProofExtract tone="band" t={t} tMeal={tMeal} />
        </div>
      </section>

      {/* 2. What the three steps name is the time given back, not the
          features. They are `<p>` rather than `<h3>`: there is no `<h2>` over
          them, and a skipped level is worse than no level.
          Tinted only on the wide layout — on the narrow one the proof band
          above already holds the tint, and two sunken bands running together
          would read as one. */}
      <section className="border-t border-border lg:bg-surface-sunken">
        <div
          className={`${BAND} flex flex-col gap-[22px] py-7 lg:grid lg:grid-cols-3 lg:gap-10 lg:pt-9 lg:pb-11`}
        >
          {([1, 2, 3] as const).map((step) => (
            <div key={step}>
              <p className="text-[11.5px] font-semibold tracking-[0.08em] text-accent lg:text-xs">
                {`0${step}`}
              </p>
              <p className="mt-[7px] text-base font-semibold lg:mt-[9px] lg:text-[17px]">
                {t(`step${step}Title`)}
              </p>
              <p className="mt-1.5 text-sm leading-[1.55] text-ink-body text-pretty lg:mt-[7px]">
                {t(`step${step}Body`)}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* 3. Guests get their own line and their own colour — `guest`, never
          `danger`, which this interface keeps for the allergen and for what
          cannot be undone. */}
      <section className="border-t border-border">
        <div className={`${BAND} flex items-start gap-3.5 py-7 lg:py-[30px]`}>
          {/* Says nothing on its own: the sentence beside it carries all of it. */}
          <span aria-hidden className="mt-2 h-2 w-2 flex-none rounded-full bg-guest" />
          <p className="text-[15.5px] leading-[1.6] text-ink-body text-pretty lg:max-w-[78ch]">
            <strong className="font-semibold text-ink">{t("guestsLead")}</strong>{" "}
            {t("guestsBody")}
          </p>
        </div>
      </section>

      {/* 4. The same single action, asked once the argument has been made. */}
      <section className="bg-accent">
        <div
          className={`${BAND} flex flex-col gap-5 pt-8 pb-[34px] lg:flex-row lg:items-center lg:justify-between lg:gap-8 lg:py-11`}
        >
          <h2 className="text-[24px] leading-[1.2] font-semibold text-accent-ink text-pretty lg:max-w-[24ch] lg:text-[28px] lg:tracking-[-0.01em]">
            {t("ctaHeading")}
          </h2>

          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a
            href="/api/auth/login"
            className={`${SIGN_IN_BUTTON} bg-surface-raised font-semibold text-accent-strong hover:bg-[color-mix(in_oklch,var(--color-accent-soft)_55%,var(--color-surface-raised))]`}
          >
            {t("button")}
          </a>
        </div>
      </section>

      {/* 5. The footer is `SiteFooter`, rendered by the layout on every screen
          including this one. Nothing to add here. */}
    </main>
  );
}

/** Two evenings of a real week, as static markup.
 *
 * Not a call to `/meal-plans`: no data exists before signing in, and this is
 * an illustration, not a preview of anyone's week. It is still marked up as a
 * list with day headings — it carries the argument, so a screen reader has to
 * be able to hear it.
 *
 * `card` is the raised panel beside the promise on a wide screen; `band` is
 * the sunken strip it becomes on a narrow one, where the slot cards invert to
 * stay lighter than what holds them. */
function ProofExtract({
  tone,
  t,
  tMeal,
  className,
}: {
  tone: "card" | "band";
  t: Awaited<ReturnType<typeof getTranslations>>;
  tMeal: Awaited<ReturnType<typeof getTranslations>>;
  className?: string;
}) {
  const raised = tone === "card";
  const slot = `flex flex-col gap-[7px] rounded-card border border-border px-[14px] py-3 lg:gap-2 ${
    raised ? "bg-surface" : "bg-surface-raised"
  }`;
  const day = "text-[13.5px] text-ink-muted lg:text-sm";
  const meal =
    "text-[11.5px] font-medium tracking-[0.05em] text-ink-muted uppercase lg:text-xs";
  const dish = "text-[15px] leading-[1.3] font-semibold text-pretty lg:text-base";

  return (
    <div
      className={cx(
        raised
          ? "rounded-card border border-border bg-surface-raised px-6 pt-[22px] pb-6 " +
              "shadow-[0_1px_2px_color-mix(in_oklab,var(--color-ink)_5%,transparent)]"
          : "pt-6 pb-[26px]",
        className,
      )}
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[11.5px] font-semibold tracking-[0.06em] text-ink-muted uppercase lg:text-xs">
          {t("proofHeading")}
        </p>
        {raised && <span className="text-[13px] text-ink-faint">{t("proofBadge")}</span>}
      </div>

      <ul className={cx("flex flex-col gap-3", raised ? "mt-4" : "mt-3.5")}>
        <li className="flex flex-col gap-2.5">
          <p className={day}>{t("proofDay1")}</p>
          <div className={slot}>
            <p className={meal}>{tMeal("dinner")}</p>
            <p className={dish}>{t("proofDish1")}</p>
            {/* The eaters show up only where they diverge — here, because
                Marceau's portion is not the same plate. */}
            <p className="text-[13px] leading-[1.45] text-ink-body text-pretty lg:text-[13.5px]">
              {t("proofVariant1")}
            </p>
            <span className="mt-0.5 self-start rounded-full bg-warn-soft px-2.5 py-1 text-[11.5px] font-medium text-ink lg:text-xs">
              {t("proofValidate")}
            </span>
          </div>
        </li>

        <li className="flex flex-col gap-2.5">
          <p className={day}>{t("proofDay2")}</p>
          <div className={slot}>
            <p className={meal}>{tMeal("dinner")}</p>
            <p className={dish}>{t("proofDish2")}</p>
            {/* The shared base, which is the whole wedge and was visible
                nowhere. */}
            <p className="flex items-center gap-[7px]">
              <span aria-hidden className="h-1.5 w-1.5 flex-none rounded-full bg-accent" />
              <span className="text-[12.5px] font-medium text-accent-hover lg:text-[13px]">
                {t("proofSharedBase")}
              </span>
            </p>
          </div>
        </li>
      </ul>

      <p
        className={cx(
          "text-[13px] leading-[1.55] text-ink-body text-pretty lg:text-[13.5px]",
          raised ? "mt-[18px] border-t border-border pt-4" : "mt-3.5",
        )}
      >
        {t("proofCaption")}
      </p>
    </div>
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
  const [plan, members, enabledSlots, invitations] = await Promise.all([
    apiGet<MealPlan | null>(`/meal-plans?week_start=${weekStart}`),
    apiGet<Member[]>("/members"),
    apiGet<MealSlot[]>("/household/slots"),
    apiGet<Invitation[]>(`/invitations?week_start=${weekStart}`),
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
    invitations: invitationsByKey(invitations ?? []),
    planId: plan?.id ?? null,
  };

  const view = resolveView((await cookies()).get(VIEW_COOKIE)?.value);

  // The open slot travels in the URL too: the back button closes the panel and
  // a reload reopens it on the same meal. A mistyped key simply leaves it shut.
  const openSlot = parseSlotKey(
    Array.isArray(search.slot) ? (search.slot[0] ?? "") : (search.slot ?? ""),
  );

  // Same story for the invitation panel: `invite=new` to create, `invite=<id>`
  // to edit one. An id that matches nothing leaves it shut.
  const inviteParam = Array.isArray(search.invite) ? search.invite[0] : search.invite;
  const editInvitation =
    inviteParam && inviteParam !== "new"
      ? ((invitations ?? []).find((invitation) => invitation.id === inviteParam) ?? null)
      : null;
  const inviteOpen = inviteParam === "new" || editInvitation !== null;

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

      {/* No reminder list under the plan any more. It existed only because
          nothing in the grid showed an invitation; now the invitation IS the
          cell, banner and all, and a list repeating it below was a third place
          to look for the same thing. */}

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

      {inviteOpen && (
        <InvitationPanel
          open
          weekStart={weekStart}
          invitation={editInvitation}
          locale={locale}
          expectedMs={EXPECTED_SECONDS * 1000}
        />
      )}
    </main>
  );
}
