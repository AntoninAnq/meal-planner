"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { Composer } from "@/components/plan/Composer";
import { GenerationError, WaitingState } from "@/components/plan/WaitingState";
import { Link, useRouter } from "@/i18n/navigation";
import { apiGet, apiPost } from "@/lib/api/client";
import { displayMessage } from "@/lib/api/error";
import type { InterpretedConstraint, MealPlan, Violation } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { slotsInViolation, splitViolations } from "@/lib/plan";
import { viewCookie, type ViewMode, type WeekView } from "@/lib/week-view";

const POLL_INTERVAL_MS = 5000;

/** Geometry only. Which one reads as current is decided in `globals.css`,
 * beside the rule that decides which view is on screen — with no explicit
 * choice the answer is a media query's, and the server cannot render it. */
const TAB =
  "rounded-none border-b-2 px-2 pb-1.5 text-sm transition-colors hover:text-ink " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

/**
 * Screen 3, and screen 4 inside it.
 *
 * The generation lives in the week view rather than in a modal: you compose
 * your week while looking at it, and a dialog would cover the very thing you
 * are commenting on. The two view trees arrive already rendered on the server
 * and are passed through as props — this component owns only what is genuinely
 * interactive.
 */
export function WeekBoard({
  initialView,
  weekStart,
  locale,
  hasPlan,
  generatedAt,
  violations,
  grid,
  list,
  favorites,
  favoritesOpen,
  expectedMs,
}: {
  initialView: ViewMode;
  weekStart: string;
  locale: string;
  hasPlan: boolean;
  generatedAt: string | null;
  violations: Violation[];
  grid: ReactNode;
  list: ReactNode;
  favorites: ReactNode;
  /** URL state, deliberately not the view cookie — see the comment at the call
   * site. Leaving the tab falls back to the remembered grid-or-list. */
  favoritesOpen: boolean;
  expectedMs: number;
}) {
  const format = useFormatter();
  const t = useTranslations("plan");
  const tFav = useTranslations("favorites");
  const tList = useTranslations("shoppingList");
  const tCommon = useTranslations("common");
  const tInv = useTranslations("invitation");
  const router = useRouter();

  const [view, setView] = useState<ViewMode>(initialView);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const busy = startedAt !== null;
  const { slot: slotViolations, plan: planViolations } = splitViolations(violations);
  // Not a failure and not shown in red: the catalogue simply holds nothing for
  // this life stage (§6.4), and the honest move is to say it once rather than
  // to mark every slot. Split out here so the alert below never counts it.
  const notPlanned = planViolations.filter((v) => v.code === "stage_not_planned");
  const otherPlanViolations = planViolations.filter((v) => v.code !== "stage_not_planned");

  function chooseView(next: WeekView) {
    setView(next);
    // A session cookie rather than sessionStorage: it is readable at render
    // time, so a reload after toggling does not flash through the media
    // query's answer before correcting itself.
    document.cookie = viewCookie(next);
    // Coming back from the favourites tab is a navigation, because that tab is
    // in the URL. The cookie is written first, so the page that arrives already
    // knows which of the two to show.
    if (favoritesOpen) router.push({ pathname: "/", query: { week: weekStart } });
  }

  const done = useCallback(() => {
    setStartedAt(null);
    setPolling(false);
    abort.current = null;
    router.refresh();
  }, [router]);

  const generate = useCallback(
    async (constraints: InterpretedConstraint[]) => {
      setError(null);
      setStartedAt(Date.now());
      const controller = new AbortController();
      abort.current = controller;

      try {
        await apiPost<MealPlan>(
          "/meal-plans",
          {
            scope: { type: "week", week_start: weekStart },
            constraints,
            language: locale,
          },
          controller.signal,
        );
        done();
      } catch (cause) {
        // An abort is the user choosing to stop waiting, not a failure: the
        // polling effect takes over from here.
        if (controller.signal.aborted) return;
        setStartedAt(null);
        setError(displayMessage(cause, tCommon));
      }
    },
    [weekStart, locale, done, tCommon],
  );

  function stopWaiting() {
    abort.current?.abort();
    setPolling(true);
  }

  // Stopping the wait loses nothing: `generate_plan` commits after the model
  // returns and the synchronous endpoint is never told the client left, so the
  // plan lands regardless. `generated_at` is the only way to tell the plan we
  // were already looking at from the one that has just arrived.
  useEffect(() => {
    if (!polling || startedAt === null) return;
    const deadline = startedAt + expectedMs * 3;

    const timer = setInterval(async () => {
      if (Date.now() > deadline) {
        setPolling(false);
        setStartedAt(null);
        setError(t("generationLost"));
        return;
      }
      try {
        const plan = await apiGet<MealPlan | null>(`/meal-plans?week_start=${weekStart}`);
        if (plan && plan.generated_at !== generatedAt) done();
      } catch {
        // A failed poll is not a failed generation. Keep waiting.
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [polling, startedAt, expectedMs, weekStart, generatedAt, done, t]);

  return (
    <div className="flex flex-col gap-5">
      {/* Two groups, not one row of controls: on the left the week and what can
          be done with it, on the right how to look at it. The shopping list is
          NOT a view, so it does not join the tabs — and not a generation
          either, so it does not join the composer. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
        {/* The page title, since the header above has none to give: the
            household name was a placeholder and there is no brand to put
            there. Formatted, not the raw ISO day — `weekOf` interpolates a
            plain string, so the date has to arrive already readable. */}
        <h1 className="text-lg font-semibold text-ink">
          {t("weekOf", {
            date: format.dateTime(new Date(`${weekStart}T12:00:00Z`), {
              day: "numeric",
              month: "long",
              year: "numeric",
            }),
          })}
        </h1>

        {/* Never offered on a week with nothing on it: there is no empty state
            for a list of nothing, and the honest way to say that is not to
            offer the button. */}
        {hasPlan && (
          <Link
            href={{ pathname: "/", query: { week: weekStart, list: "1" } }}
            className={cx(
              "rounded-control px-2 py-1 text-sm font-medium text-ink-muted",
              "transition-colors hover:bg-surface-sunken hover:text-ink",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
            )}
          >
            {tList("open")}
          </Link>
        )}
        </div>

        {/* Three tabs now, and they stopped being buttons-that-look-pressed:
            an underline says "you are here" without borrowing the weight of
            the primary action, which on this screen is generating a week. */}
        <div
          className="flex items-center gap-1"
          role="group"
          aria-label={t("viewLabel")}
          data-tabs={favoritesOpen ? "favorites" : view}
        >
          {(["grid", "list"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              data-tab={mode}
              onClick={() => chooseView(mode)}
              // Left off while the view is `auto`: nothing here knows which of
              // the two the media query landed on, and announcing the wrong one
              // is worse than announcing neither. One click settles it.
              aria-current={!favoritesOpen && view === mode ? "true" : undefined}
              className={TAB}
            >
              {t(`view.${mode}`)}
            </button>
          ))}
          <Link
            href={{ pathname: "/", query: { week: weekStart, view: "favorites" } }}
            data-tab="favorites"
            aria-current={favoritesOpen ? "true" : undefined}
            className={TAB}
          >
            {tFav("tab")}
          </Link>
        </div>
      </div>

      <Composer
        hasPlan={hasPlan}
        busy={busy}
        onGenerate={generate}
        inviteAction={
          // Geometry of `ui/Button.tsx`, variant secondary, reproduced because
          // this is a link and that primitive renders a `<button>`.
          <Link
            href={{ pathname: "/", query: { week: weekStart, invite: "new" } }}
            className={cx(
              "inline-flex h-10 items-center justify-center rounded-control border border-border",
              "bg-surface-raised px-4 text-sm font-medium text-ink transition-colors",
              "hover:bg-surface-sunken focus-visible:outline-2 focus-visible:outline-offset-2",
              "focus-visible:outline-accent",
            )}
          >
            {tInv("create")}
          </Link>
        }
      />

      {/* Both notices point at cells — "ils sont signalés dans la semaine" —
          and on the favourites tab there is no week on screen to point at.
          They come back with the grid. */}
      {notPlanned.length > 0 && !busy && !favoritesOpen && (
        <div role="note" className="rounded-card border border-border bg-surface-sunken px-4 py-3">
          <p className="text-sm font-semibold">{t("notPlannedHeading")}</p>
          <p className="mt-1 text-sm text-ink-muted">{t("notPlannedBody")}</p>
        </div>
      )}

      {(slotViolations.length > 0 || otherPlanViolations.length > 0) && !busy && !favoritesOpen && (
        <div role="alert" className="rounded-card border border-danger/30 bg-danger-soft px-4 py-3">
          {/* Two different failures, two different sentences. A plan-level
              violation points at no meal, so counting it as "a meal could not
              be completed" would send the user hunting for a slot that is
              perfectly fine. */}
          {slotViolations.length > 0 && (
            <>
              <p className="text-sm font-semibold text-danger">
                {t("violationsHeading", { count: slotsInViolation(slotViolations) })}
              </p>
              <p className="mt-1 text-sm text-ink">{t("violationsBody")}</p>
            </>
          )}
          {otherPlanViolations.length > 0 && (
            <>
              <p
                className={cx(
                  "text-sm font-semibold text-danger",
                  slotViolations.length > 0 && "mt-3",
                )}
              >
                {t("planViolationHeading")}
              </p>
              <p className="mt-1 text-sm text-ink">{t("planViolationBody")}</p>
            </>
          )}
        </div>
      )}

      {favoritesOpen ? (
        // In the grid's place: it is a third way of looking at what the
        // household has, not a page of its own. The composer above stays —
        // generating a week from here is not a mistake to prevent.
        favorites
      ) : busy ? (
        <WaitingState
          startedAt={startedAt}
          expectedMs={expectedMs}
          polling={polling}
          onStopWaiting={stopWaiting}
        />
      ) : error ? (
        // In the grid's place, not above it: a failure about the week belongs
        // where the week was going to be. Retrying re-opens the composer rather
        // than firing a second generation blind — the constraints are still
        // there, and the reason it failed may be one of them.
        <GenerationError message={error} onRetry={() => setError(null)} />
      ) : (
        // Both trees are in the DOM; globals.css decides. Without an explicit
        // choice the attribute is `auto` and the media query answers, which is
        // what makes the first paint right on any device.
        <div data-view={view} className={cx("min-w-0")}>
          <div data-week-view="grid">{grid}</div>
          <div data-week-view="list">{list}</div>
        </div>
      )}
    </div>
  );
}
