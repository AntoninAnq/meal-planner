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
 */
export function VariantConfirm({
  planId,
  dishId,
  memberId,
  name,
  confirmed,
}: {
  planId: string;
  dishId: string;
  memberId: string;
  name: string;
  confirmed: boolean;
}) {
  const t = useTranslations("plan");
  const router = useRouter();
  const [pending, start] = useTransition();
  const [failed, setFailed] = useState(false);

  function toggle() {
    setFailed(false);
    start(async () => {
      try {
        await apiPost(`/meal-plans/${planId}/dishes/${dishId}/variant-confirmation`, {
          member_id: memberId,
          confirmed: !confirmed,
        });
        router.refresh();
      } catch {
        // Silent failure here would leave the parent believing they confirmed.
        setFailed(true);
      }
    });
  }

  return (
    <span className="pointer-events-auto relative z-10 inline-flex items-center gap-1.5">
      <button
        type="button"
        onClick={toggle}
        disabled={pending}
        aria-pressed={confirmed}
        className={cx(
          "rounded-full px-2 py-0.5 text-xs transition-colors disabled:opacity-50",
          "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
          confirmed
            ? "bg-surface-sunken text-ink-muted hover:text-ink"
            : "bg-warn-soft text-ink font-medium hover:brightness-95",
        )}
      >
        {confirmed ? t("variantConfirmed") : t("variantConfirm", { name })}
      </button>
      {failed && <span className="text-xs text-danger">{t("variantConfirmFailed")}</span>}
    </span>
  );
}
