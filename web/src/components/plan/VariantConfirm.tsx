"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";

import { useRouter } from "@/i18n/navigation";
import { apiPost } from "@/lib/api/client";
import { cx } from "@/lib/cx";

/**
 * The one thing between "a model wrote a serving instruction" and "a
 * 16-month-old is served an adult dish".
 *
 * No catalogue recipe suits a baby — zero of 3 439 — so every baby plate is an
 * adaptation of an adult dish, proposed by a model that cannot judge texture.
 * `ARCHITECTURE.md` §4.9 keeps I1 intact by moving the decision to the parent
 * rather than pretending the system made it: what is confirmed here is that
 * THIS texture suits THIS child.
 *
 * Deliberately not a nice reassuring button. An unconfirmed variant looks
 * unfinished, because it is — and a plate that looks like the eight others
 * would be read as vouched for by the system, which is the one thing it is not.
 *
 * With NO variant, which is what Haiku produces — 45 generations out of 45 —
 * this also offers to write one. Optional, and said so: the household knows
 * what it will do with the baby's plate, and a field it must fill to clear a
 * mark would be a toll, not a safety measure. The sentence is for whoever
 * cooks on Thursday.
 */
export function VariantConfirm({
  planId,
  dishId,
  memberId,
  name,
  variant,
  confirmed,
}: {
  planId: string;
  dishId: string;
  memberId: string;
  name: string;
  /** Null when nothing describes this plate yet. */
  variant: string | null;
  confirmed: boolean;
}) {
  const t = useTranslations("plan");
  const router = useRouter();
  const [pending, start] = useTransition();
  const [failed, setFailed] = useState(false);
  const [draft, setDraft] = useState("");

  function send(next: boolean, text?: string) {
    setFailed(false);
    start(async () => {
      try {
        await apiPost(`/meal-plans/${planId}/dishes/${dishId}/variant-confirmation`, {
          member_id: memberId,
          confirmed: next,
          ...(text ? { variant: text } : {}),
        });
        router.refresh();
      } catch {
        // Silent failure here would leave the parent believing they confirmed.
        setFailed(true);
      }
    });
  }

  const button = (
    <button
      type="button"
      onClick={() => send(!confirmed, draft.trim() || undefined)}
      disabled={pending}
      aria-pressed={confirmed}
      // The variant line right above already names the person, so repeating
      // it on the button made the card stutter. The name stays in the
      // accessible name, where the button is read out of that context.
      aria-label={t("variantConfirm", { name })}
      className={cx(
        "rounded-full px-[9px] py-[3px] text-[11.5px] leading-[1.4] whitespace-nowrap",
        "transition-colors disabled:opacity-50",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        confirmed
          ? "bg-surface-sunken text-ink-muted hover:text-ink"
          : "bg-warn-soft text-ink font-medium hover:brightness-95",
      )}
    >
      {confirmed ? t("variantConfirmed") : t("variantConfirmShort")}
    </button>
  );

  return (
    <span className="pointer-events-auto relative z-10 inline-flex items-center gap-1.5">
      {/* Only where there is nothing to read: a plate the model described is
          confirmed as it stands, and an input beside it would ask the parent
          to rewrite what they were meant to be judging. */}
      {variant === null && !confirmed && (
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={t("variantWritePlaceholder")}
          aria-label={t("variantWriteLabel", { name })}
          className={cx(
            "h-7 w-[min(46vw,15rem)] rounded-control border border-border bg-surface px-2",
            "text-[12.5px] text-ink placeholder:text-ink-faint",
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
          )}
        />
      )}
      {button}
      {failed && <span className="text-xs text-danger">{t("variantConfirmFailed")}</span>}
    </span>
  );
}
