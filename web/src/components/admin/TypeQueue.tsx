"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { apiPut } from "@/lib/api/client";
import { cx } from "@/lib/cx";
import type { DishType, RecipeToType } from "@/lib/api/types";

/** In the order they are pressed, and the order the keys are numbered.
 *
 * `main` first because most of what reaches this queue is a main; `component`
 * last because it is the one people forget exists — a vinaigrette is a
 * catalogue recipe and not a meal, and without that answer it lands in
 * "not labelled dessert", which is to say in the dinner candidates. */
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
 * One recipe at a time, decided with one key.
 *
 * A list of a hundred and thirty rows invites scrolling and second-guessing;
 * a single card invites a decision. The work is repetitive by nature — the
 * ingredients almost always settle it in a second — so the interface is built
 * for cadence: read, press a digit, next.
 *
 * The queue is held in state and advanced locally rather than refetched after
 * each decision. A round trip between two cards would make the rhythm the
 * network's rather than the reader's, and the server is not the authority on
 * what has already been shown.
 */
export function TypeQueue({ initial }: { initial: RecipeToType[] }) {
  const t = useTranslations("admin");
  const [queue, setQueue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const current = queue[0];

  const decide = useCallback(
    async (dishType: DishType) => {
      if (!current || busy) return;
      setBusy(true);
      setFailed(false);
      try {
        await apiPut(`/admin/recipes/${current.id}/dish-type`, { dish_type: dishType });
        setQueue((rest) => rest.slice(1));
      } catch {
        // The card stays. Advancing on a failed write would lose the decision
        // and the recipe in the same gesture, and nothing on screen would say
        // which one went missing.
        setFailed(true);
      } finally {
        setBusy(false);
      }
    },
    [current, busy],
  );

  // Digits, because the hands never leave them. Ignored while typing anywhere
  // else, so the shortcut cannot fire from a field that does not exist yet.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
      const index = Number(event.key) - 1;
      if (Number.isInteger(index) && index >= 0 && index < TYPES.length) {
        event.preventDefault();
        void decide(TYPES[index]);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [decide]);

  if (!current) {
    return <p className="text-sm text-ink-muted">{t("done")}</p>;
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-ink-muted" aria-live="polite">
        {t("remaining", { count: queue.length })}
      </p>

      <article className="flex flex-col gap-4 rounded-card border border-border bg-surface-raised px-5 py-5">
        <div>
          <h2 className="text-xl leading-[1.25] font-semibold text-pretty">{current.title}</h2>
          <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-ink-muted">
            <span>
              {t("rubric")} :{" "}
              {current.source_categories.length > 0 ? (
                <span className="text-ink-body">{current.source_categories.join(", ")}</span>
              ) : (
                <span className="italic">{t("noRubric")}</span>
              )}
            </span>
            {current.minutes !== null && <span>· {current.minutes} min</span>}
            {current.source_url && (
              <a
                href={current.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="rounded-full bg-surface-sunken px-2 py-0.5 underline-offset-2 hover:bg-accent-soft hover:text-accent"
              >
                {t("source")} ↗
              </a>
            )}
          </p>
        </div>

        {/* What actually decides it. Rhubarb and sugar is a dessert; butter,
            honey and mustard is a component. */}
        {current.ingredients.length > 0 && (
          <p className="text-[15px] leading-[1.5] text-ink-body text-pretty">
            <span className="font-medium text-ink">{t("ingredients")} : </span>
            {current.ingredients.join(", ")}
          </p>
        )}
      </article>

      <div className="flex flex-wrap gap-2">
        {TYPES.map((type, index) => (
          <Button
            key={type}
            variant="secondary"
            disabled={busy}
            onClick={() => decide(type)}
            className={cx("gap-2", busy && "opacity-60")}
          >
            <span className="rounded-control bg-surface-sunken px-1.5 text-xs text-ink-muted">
              {index + 1}
            </span>
            {t(`dishType.${type}`)}
          </Button>
        ))}
      </div>

      <p className="text-[13px] text-ink-muted">{t("shortcut")}</p>
      {failed && (
        <p role="alert" className="text-sm text-danger">
          {t("failed")}
        </p>
      )}
    </div>
  );
}
