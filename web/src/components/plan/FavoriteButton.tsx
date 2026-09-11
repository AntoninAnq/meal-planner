"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";

import { useRouter } from "@/i18n/navigation";
import { apiDelete, apiPost } from "@/lib/api/client";
import { cx } from "@/lib/cx";

/**
 * "Mettre en favori" / "En favori", as a word rather than a heart.
 *
 * The product loads no icon anywhere — no font, no SVG, no image — and
 * introducing one for this single function would create a visual dependency
 * for something a word says better. A dish that came from the model alone
 * renders NOTHING here: no greyed control, no tooltip. The rule is explained
 * once, on the empty state, and an affordance that exists only to be refused
 * teaches people to stop looking.
 *
 * Lives in the slot panel and nowhere else. The grid was just stripped of
 * everything that does not vary (UX §5); putting a control back on every card
 * would undo that, and the panel is one click away and already the place where
 * a dish is inspected.
 */
export function FavoriteToggle({
  recipeId,
  title,
  favorited,
  className,
}: {
  recipeId: string;
  title: string;
  favorited: boolean;
  className?: string;
}) {
  const t = useTranslations("favorites");
  const router = useRouter();
  const [pending, start] = useTransition();
  const [failed, setFailed] = useState(false);

  function toggle() {
    setFailed(false);
    start(async () => {
      try {
        if (favorited) {
          await apiDelete(`/favorites/${recipeId}`);
        } else {
          await apiPost("/favorites", { recipe_id: recipeId });
        }
        router.refresh();
      } catch {
        // Silent failure would leave someone believing the dish was saved.
        setFailed(true);
      }
    });
  }

  return (
    <span className={cx("inline-flex items-center gap-2", className)}>
      <button
        type="button"
        onClick={toggle}
        disabled={pending}
        aria-pressed={favorited}
        aria-label={favorited ? t("removeLabel", { title }) : undefined}
        className={cx(
          "inline-flex h-8 items-center rounded-control px-3 text-[13px] font-medium",
          "transition-colors disabled:cursor-not-allowed disabled:opacity-50",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          favorited
            ? "border border-border bg-surface-sunken text-ink"
            : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
        )}
      >
        {favorited ? t("added") : t("add")}
      </button>
      {failed && <span className="text-xs text-danger">{t("failed")}</span>}
    </span>
  );
}

/**
 * The tab's own control, which says "Retirer" rather than toggling.
 *
 * No confirmation: the action is undone with one click from any slot panel,
 * and a modal would cost more attention than the mistake it prevents. What it
 * does owe is a response — the row goes, and the count above it follows.
 */
export function FavoriteRemove({ recipeId, title }: { recipeId: string; title: string }) {
  const t = useTranslations("favorites");
  const router = useRouter();
  const [pending, start] = useTransition();
  const [failed, setFailed] = useState(false);

  function remove() {
    setFailed(false);
    start(async () => {
      try {
        await apiDelete(`/favorites/${recipeId}`);
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
        onClick={remove}
        disabled={pending}
        aria-label={t("removeLabel", { title })}
        className={cx(
          "rounded-control px-1.5 py-1 text-[13px] text-ink-muted transition-colors",
          "hover:text-ink disabled:cursor-not-allowed disabled:opacity-50",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        )}
      >
        {t("remove")}
      </button>
    </span>
  );
}
