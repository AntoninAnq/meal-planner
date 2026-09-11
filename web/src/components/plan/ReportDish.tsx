"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { apiPost } from "@/lib/api/client";
import type { ReportCategory } from "@/lib/api/types";

/** In the order they happen. `not_a_meal` first because it is the commonest —
 * a rubric the mapping cannot read leaves a dessert eligible for a Thursday. */
const CATEGORIES: ReportCategory[] = ["not_a_meal", "dead_link", "bad_recipe"];

/**
 * "This is wrong for everyone" — deliberately not the same thing as a refusal.
 *
 * `Proposer autre chose`, further down, records why THIS household said no and
 * turns it into a constraint of theirs; `Ne plus me proposer`, beside the
 * favourite, is a matter of taste. This says the catalogue entry is at fault,
 * and its resolution changes what every household is offered. It sits at the
 * end of the dish it is about, small and folded away — under the suggestions
 * it read as a report on one of them — and its label names the recipe, so it
 * is not taken for a third way of saying "not for us".
 *
 * Folded rather than absent, because a household that has just been served a
 * cake for dinner needs somewhere to put that, and the alternative is a bug
 * report nobody writes.
 */
export function ReportDish({
  planId,
  dishId,
  onReported,
}: {
  planId: string;
  dishId: string;
  onReported?: () => void;
}) {
  const t = useTranslations("panel");
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function report(category: ReportCategory) {
    setBusy(true);
    try {
      await apiPost(`/meal-plans/${planId}/dishes/${dishId}/report`, { category });
      setSent(true);
      setOpen(false);
      onReported?.();
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return <p className="text-xs text-ink-muted">{t("reportDone")}</p>;
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="self-start text-xs text-ink-faint underline underline-offset-2 transition-colors hover:text-ink-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {t("reportOpen")}
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-control border border-border bg-surface-sunken px-3 py-2.5">
      <p className="text-xs leading-[1.45] text-ink-body text-pretty">{t("reportHint")}</p>
      <div className="flex flex-col gap-1.5">
        {CATEGORIES.map((category) => (
          <Button
            key={category}
            size="sm"
            disabled={busy}
            className="justify-start"
            onClick={() => report(category)}
          >
            {t(`reportCategory.${category}`)}
          </Button>
        ))}
      </div>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="self-start text-xs text-ink-muted underline underline-offset-2"
      >
        {t("reportCancel")}
      </button>
    </div>
  );
}
