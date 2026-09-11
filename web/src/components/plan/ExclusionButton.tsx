"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";

import { useRouter } from "@/i18n/navigation";
import { apiDelete, apiPost } from "@/lib/api/client";
import { cx } from "@/lib/cx";

/**
 * "Ne plus me proposer" / "Reproposer", beside the favourite it is the
 * opposite of.
 *
 * It replaced "Ce plat a plu ?", whose answer nothing read: a household said no
 * and the dish came back the next week. This one acts on the pool the week and
 * the alternatives are drawn from. The dish already on the plan stays — the
 * button is often pressed after the meal was eaten — and the panel marks it.
 */
export function ExclusionToggle({
  recipeId,
  title,
  excluded,
}: {
  recipeId: string;
  title: string;
  excluded: boolean;
}) {
  const t = useTranslations("exclusions");
  const router = useRouter();
  const [pending, start] = useTransition();
  const [failed, setFailed] = useState(false);

  function toggle() {
    setFailed(false);
    start(async () => {
      try {
        if (excluded) {
          await apiDelete(`/exclusions/${recipeId}`);
        } else {
          await apiPost("/exclusions", { recipe_id: recipeId });
        }
        router.refresh();
      } catch {
        // Silent failure would leave someone believing the dish is gone for good.
        setFailed(true);
      }
    });
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={toggle}
        disabled={pending}
        aria-pressed={excluded}
        aria-label={excluded ? t("restoreLabel", { title }) : undefined}
        className={cx(
          "inline-flex h-8 items-center rounded-control px-3 text-[13px] font-medium",
          "text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        )}
      >
        {excluded ? t("restore") : t("exclude")}
      </button>
      {failed && <span className="text-xs text-danger">{t("failed")}</span>}
    </span>
  );
}

/** The tab's own control: "Reproposer", and the row leaves the list. */
export function ExclusionRestore({ recipeId, title }: { recipeId: string; title: string }) {
  const t = useTranslations("exclusions");
  const router = useRouter();
  const [pending, start] = useTransition();
  const [failed, setFailed] = useState(false);

  function restore() {
    setFailed(false);
    start(async () => {
      try {
        await apiDelete(`/exclusions/${recipeId}`);
        router.refresh();
      } catch {
        setFailed(true);
      }
    });
  }

  return (
    <span className="inline-flex flex-none items-center gap-2">
      {failed && <span className="text-xs text-danger">{t("failed")}</span>}
      <button
        type="button"
        onClick={restore}
        disabled={pending}
        aria-label={t("restoreLabel", { title })}
        className={cx(
          "rounded-control px-1.5 py-1 text-[13px] text-ink-muted transition-colors",
          "hover:text-ink disabled:cursor-not-allowed disabled:opacity-50",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        )}
      >
        {t("restore")}
      </button>
    </span>
  );
}
