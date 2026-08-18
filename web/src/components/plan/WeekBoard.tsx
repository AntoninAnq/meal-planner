"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { Composer } from "@/components/plan/Composer";
import { WaitingState } from "@/components/plan/WaitingState";
import { Button } from "@/components/ui/Button";
import { useRouter } from "@/i18n/navigation";
import { apiGet, apiPost } from "@/lib/api/client";
import { ApiError } from "@/lib/api/error";
import type { MealPlan, Violation } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { slotsInViolation, splitViolations } from "@/lib/plan";
import { viewCookie, type ViewMode, type WeekView } from "@/lib/week-view";

const POLL_INTERVAL_MS = 5000;

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
  expectedMs: number;
}) {
  const t = useTranslations("plan");
  const tCommon = useTranslations("common");
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
  }

  const done = useCallback(() => {
    setStartedAt(null);
    setPolling(false);
    abort.current = null;
    router.refresh();
  }, [router]);

  const generate = useCallback(
    async (constraints: string[]) => {
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
        setError(cause instanceof ApiError ? cause.message : tCommon("genericError"));
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm text-ink-muted">{t("weekOf", { date: weekStart })}</h2>

        <div className="flex gap-1" role="group" aria-label={t("viewLabel")}>
          {(["grid", "list"] as const).map((mode) => (
            <Button
              key={mode}
              size="sm"
              variant={view === mode ? "primary" : "ghost"}
              onClick={() => chooseView(mode)}
            >
              {t(`view.${mode}`)}
            </Button>
          ))}
        </div>
      </div>

      <Composer hasPlan={hasPlan} busy={busy} onGenerate={generate} />

      {notPlanned.length > 0 && !busy && (
        <div role="note" className="rounded-card border border-border bg-surface-sunken px-4 py-3">
          <p className="text-sm font-semibold">{t("notPlannedHeading")}</p>
          <p className="mt-1 text-sm text-ink-muted">{t("notPlannedBody")}</p>
        </div>
      )}

      {(slotViolations.length > 0 || otherPlanViolations.length > 0) && !busy && (
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

      {error && <p className="text-sm text-danger">{error}</p>}

      {busy ? (
        <WaitingState
          startedAt={startedAt}
          expectedMs={expectedMs}
          polling={polling}
          onStopWaiting={stopWaiting}
        />
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
