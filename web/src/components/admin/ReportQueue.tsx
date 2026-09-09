"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { apiPost, apiPut } from "@/lib/api/client";
import type { DishType, ReportedRecipe } from "@/lib/api/types";

/** Same order and same keys as the typing queue: the commonest answer to a
 * report is a dish type, and the hands should not have to relearn where they
 * are between the two screens. */
const TYPES: DishType[] = [
  "main",
  "starter",
  "side",
  "dessert",
  "snack",
  "breakfast",
  "drink",
  "component",
];

/**
 * What households said is wrong, and the three ways it ends.
 *
 * Retagging is first and largest because `not_a_meal` is what most reports
 * say — a rubric the mapping cannot read leaves a dessert eligible for a
 * Thursday dinner. Withdrawing is for a dead link or an unusable recipe.
 * Dismissing is for a report that was mistaken, and it exists because a queue
 * that only grows stops being read.
 *
 * All three close the reports on that recipe server-side, so the operator never
 * does the work and is then asked to record that they did it.
 */
export function ReportQueue({ initial }: { initial: ReportedRecipe[] }) {
  const t = useTranslations("admin");
  const [queue, setQueue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const current = queue[0];

  async function act(run: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      await run();
      setQueue((rest) => rest.slice(1));
    } catch {
      // The card stays: advancing on a failed write would lose the decision
      // and the recipe together, with nothing on screen saying which.
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  if (!current) {
    return <p className="text-sm text-ink-muted">{t("reportsDone")}</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <article className="flex flex-col gap-3 rounded-card border border-border bg-surface-raised px-5 py-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-lg leading-[1.25] font-semibold text-pretty">{current.title}</h3>
          <span className="text-[13px] text-ink-muted">
            {t("households", { count: current.households })}
          </span>
        </div>

        <ul className="flex flex-wrap gap-1.5">
          {current.categories.map((category) => (
            <li
              key={category}
              className="rounded-full bg-warn-soft px-2.5 py-1 text-xs font-medium text-ink"
            >
              {t(`reportCategory.${category}`)}
            </li>
          ))}
        </ul>

        {/* The one report in twenty that says something a category cannot. */}
        {current.notes.length > 0 && (
          <ul className="flex flex-col gap-1 text-[13px] leading-[1.45] text-ink-body">
            {current.notes.map((note, index) => (
              <li key={index}>« {note} »</li>
            ))}
          </ul>
        )}

        {current.source_url && (
          <a
            href={current.source_url}
            target="_blank"
            rel="noreferrer noopener"
            className="self-start rounded-full bg-surface-sunken px-2 py-0.5 text-xs text-ink-muted hover:bg-accent-soft hover:text-accent"
          >
            {t("source")} ↗
          </a>
        )}
      </article>

      <div className="flex flex-wrap gap-2">
        {TYPES.map((type) => (
          <Button
            key={type}
            variant="secondary"
            disabled={busy}
            onClick={() =>
              act(() =>
                apiPut(`/admin/recipes/${current.recipe_id}/dish-type`, { dish_type: type }),
              )
            }
          >
            {t(`dishType.${type}`)}
          </Button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2 border-t border-border pt-3">
        <Button
          variant="danger"
          disabled={busy}
          onClick={() => act(() => apiPost(`/admin/recipes/${current.recipe_id}/withdraw`, {}))}
        >
          {t("withdraw")}
        </Button>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => act(() => apiPost(`/admin/reports/${current.recipe_id}/dismiss`, {}))}
        >
          {t("dismiss")}
        </Button>
      </div>

      {failed && (
        <p role="alert" className="text-sm text-danger">
          {t("failed")}
        </p>
      )}
    </div>
  );
}
