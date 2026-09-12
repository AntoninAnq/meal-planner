"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { apiPost } from "@/lib/api/client";
import type { PendingRecipe } from "@/lib/api/types";

/** Why a recipe is not taken, in the order they happen. The author reads the
 * reason, so it comes from a closed list rather than from an operator's own
 * words. */
const REASONS = ["not_a_meal", "copied", "unusable"] as const;

/**
 * What households wrote, and whether it leaves their kitchen.
 *
 * The method is shown in full, and that is the point: sharing publishes it to
 * every household, so the one question this screen exists to answer is whether
 * the text was written here or copied off a site. A link, when the author gave
 * one, is the strongest hint there is.
 *
 * Refusing costs the author nothing — the recipe stays theirs and stays
 * usable — which is why the buttons say what they say rather than "delete".
 */
export function RecipeQueue({ initial }: { initial: PendingRecipe[] }) {
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
      // and the recipe together.
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  if (!current) {
    return <p className="text-sm text-ink-muted">{t("pendingDone")}</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <article className="flex flex-col gap-3 rounded-card border border-border bg-surface-raised px-5 py-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-lg leading-[1.25] font-semibold text-pretty">{current.title}</h3>
          <span className="text-[13px] text-ink-muted">
            {current.servings_raw ?? t("noServings")}
          </span>
        </div>

        {current.lines.length > 0 && (
          <ul className="flex flex-col gap-0.5 text-[13px] leading-[1.45] text-ink-body">
            {current.lines.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        )}

        {/* Read before it is published, not after a complaint. */}
        {current.instructions && (
          <p className="rounded-control bg-surface-sunken px-3 py-2.5 text-[13px] leading-[1.5] whitespace-pre-line text-ink-body">
            {current.instructions}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3">
          {current.source_url && (
            <a
              href={current.source_url}
              target="_blank"
              rel="noreferrer noopener"
              className="rounded-full bg-warn-soft px-2.5 py-1 text-xs text-ink hover:brightness-95"
            >
              {t("declaredSource")} ↗
            </a>
          )}
          <span className="text-xs text-ink-muted">
            {current.allergens_verified ? t("recipeVerified") : t("recipeUnverified")}
          </span>
        </div>
      </article>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => act(() => apiPost(`/admin/recipes/${current.recipe_id}/share`, {}))}
        >
          {t("share")}
        </Button>
      </div>

      <div className="flex flex-wrap gap-2 border-t border-border pt-3">
        {REASONS.map((reason) => (
          <Button
            key={reason}
            variant="secondary"
            disabled={busy}
            onClick={() =>
              act(() =>
                apiPost(`/admin/recipes/${current.recipe_id}/reject`, { reason }),
              )
            }
          >
            {t(`reject.${reason}`)}
          </Button>
        ))}
      </div>

      {failed && (
        <p role="alert" className="text-sm text-danger">
          {t("failed")}
        </p>
      )}
    </div>
  );
}
