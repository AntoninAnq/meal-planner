"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { playfulIndex, waitPhase } from "@/lib/waiting";

/** How many light messages exist per locale. Keep in step with the `waiting.playful.*` keys. */
const PLAYFUL_COUNT = 5;

/**
 * Shown where the grid is, so the wait happens where the result will appear.
 *
 * There is nothing to stream — the model emits identifiers and returns in one
 * block — so there is nothing real to measure. No bar, no percentage: a bar
 * that advances on its own and then sits at 90% is worse than no bar.
 */
export function WaitingState({
  startedAt,
  expectedMs,
  polling,
  onStopWaiting,
}: {
  startedAt: number;
  expectedMs: number;
  polling: boolean;
  onStopWaiting: () => void;
}) {
  const t = useTranslations("waiting");
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const tick = () => setElapsed(Date.now() - startedAt);
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [startedAt]);

  const phase = waitPhase(elapsed, expectedMs);

  const message =
    phase === "playful"
      ? t(`playful.${playfulIndex(elapsed, PLAYFUL_COUNT)}`)
      : phase === "slow"
        ? t("slow")
        : t("stalled");

  return (
    <div className="flex flex-col items-center gap-4 rounded-card border border-dashed border-border px-6 py-16 text-center">
      {phase !== "stalled" && <Spinner label={t("srLabel")} className="size-6 text-accent" />}

      <p className="text-lg font-medium text-balance">{message}</p>

      {phase === "playful" && (
        <p className="text-sm text-ink-muted">
          {t("announced", { seconds: Math.round(expectedMs / 1000) })}
        </p>
      )}

      {polling && <p className="text-sm text-ink-muted">{t("stillCooking")}</p>}

      {/* Not "cancel": the endpoint is synchronous and is never told the client
          left, so the plan will be written either way. A button that claims to
          cancel would make the user relaunch, and the second generation would
          overwrite the first. */}
      {phase !== "playful" && !polling && (
        <Button variant="secondary" onClick={onStopWaiting}>
          {t("stopWaiting")}
        </Button>
      )}
    </div>
  );
}
