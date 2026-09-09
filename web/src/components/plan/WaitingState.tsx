"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { playfulIndex, waitPhase } from "@/lib/waiting";

/** How many light messages exist per locale. Keep in step with the `waiting.playful.*` keys. */
const PLAYFUL_COUNT = 5;

/** Past this, a duration is read in minutes. Below it, seconds are what people
 * count in — "environ 90 secondes" is a wait you sit through, "1 minute" is a
 * wait you leave. */
const READS_IN_MINUTES = 90;

/** The expected duration, in a unit that survives its own configuration.
 *
 * `expectedMs` is a deployment setting — 30 s on the cloud model, 182 measured
 * on the local 8B — so the sentence has to hold at every value it can take. It
 * did not: the French string interpolated the number into "-aine", which reads
 * "une 30aine de secondes" on the cloud and "une 180aine" on the local model.
 * Only visible by rendering it, which is how it was found. */
function announce(t: (key: string, values?: Record<string, number>) => string, expectedMs: number) {
  const seconds = Math.round(expectedMs / 1000);
  return seconds < READS_IN_MINUTES
    ? t("announcedSeconds", { seconds })
    : t("announcedMinutes", { minutes: Math.round(seconds / 60) });
}

/** The place where the result is going to appear.
 *
 * Everything about a generation — the wait, the stall, the failure — is drawn
 * here, in the grid's own space. Not an overlay, not a red line at the top of
 * the page: an error about the week belongs where the week goes, or the user
 * reads it and then has to work out what it was about. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3.5 rounded-card border border-dashed border-border px-6 py-11 text-center">
      {children}
    </div>
  );
}

/**
 * Shown where the grid is, so the wait happens where the result will appear.
 *
 * There is nothing to stream — the model emits identifiers and returns in one
 * block — so there is nothing real to measure. No bar, no percentage: a bar
 * that advances on its own and then sits at 90% is worse than no bar. Every
 * threshold derives from `expectedMs`, which is configuration: thirty seconds
 * on the cloud model, 182 measured on the local 8B.
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

  // Someone who stopped waiting is not in a failure and not in a hurry: the
  // generation is finishing on the server either way, so what they need is the
  // reassurance, not the stall message the clock would otherwise produce.
  const heading = polling
    ? t("stillCooking")
    : phase === "playful"
      ? t(`playful.${playfulIndex(elapsed, PLAYFUL_COUNT)}`)
      : phase === "slow"
        ? t("slow")
        : t("stalled");

  const detail = polling
    ? t("stillCookingBody")
    : phase === "playful"
      ? announce(t, expectedMs)
      : null;

  return (
    <Frame>
      {phase !== "stalled" && <Spinner label={t("srLabel")} className="size-6 text-accent" />}

      <p className="text-[17px] leading-[1.35] font-medium text-balance">{heading}</p>

      {detail && (
        <p className="text-[13.5px] leading-[1.45] text-ink-body text-pretty">{detail}</p>
      )}

      {/* Not "cancel": the endpoint is synchronous and is never told the client
          left, so the plan will be written either way. A button that claims to
          cancel would make the user relaunch, and the second generation would
          overwrite the first. It appears only once the wait is longer than
          expected — offering it at second three would invite the very thing it
          is there to survive. */}
      {phase !== "playful" && !polling && (
        <Button variant="secondary" onClick={onStopWaiting}>
          {t("stopWaiting")}
        </Button>
      )}
    </Frame>
  );
}

/**
 * The third state: it did not go through.
 *
 * Same frame as the wait, because it answers the same question — where is my
 * week. The message comes from `common`, so a quota refusal reads as a quota
 * refusal: trying again immediately would not help, and a generic "something
 * went wrong" would have the household hammering the button.
 */
export function GenerationError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  const t = useTranslations("waiting");

  return (
    <Frame>
      <p className="text-[17px] leading-[1.35] font-medium text-balance">{t("failed")}</p>
      <p role="alert" className="text-[13.5px] leading-[1.45] text-danger text-pretty">
        {message}
      </p>
      <Button variant="secondary" onClick={onRetry}>
        {t("retry")}
      </Button>
    </Frame>
  );
}
