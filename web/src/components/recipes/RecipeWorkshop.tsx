"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { useRouter } from "@/i18n/navigation";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api/client";
import { displayMessage } from "@/lib/api/error";
import type { HouseholdRecipe, IngredientMatch } from "@/lib/api/types";
import { cx } from "@/lib/cx";

const TEXTAREA =
  "w-full rounded-control border border-border bg-surface-raised px-3 py-2 text-sm " +
  "text-ink placeholder:text-ink-faint focus:border-border-strong " +
  "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent";

type Draft = {
  id: string | null;
  title: string;
  servings: string;
  lines: string;
  instructions: string;
  source_url: string;
};

const EMPTY: Draft = { id: null, title: "", servings: "", lines: "", instructions: "", source_url: "" };

function toDraft(recipe: HouseholdRecipe): Draft {
  return {
    id: recipe.id,
    title: recipe.title,
    servings: recipe.servings ? String(recipe.servings) : "",
    lines: recipe.lines.map((line) => line.raw).join("\n"),
    instructions: recipe.instructions ?? "",
    source_url: recipe.source_url ?? "",
  };
}

/**
 * Writing down a dish the catalogue does not carry.
 *
 * The form asks for a title and nothing else. "Steak purée" is a legitimate
 * answer to "what are we eating", and a form that demands quantities before it
 * accepts that is a form nobody fills in — the quantities are offered, with
 * what they buy said next to them: a shopping list adjusted to the table.
 *
 * The ingredient search writes INTO the list rather than replacing it. A line
 * the referential recognises is what makes a recipe verifiable, and the honest
 * way to get one is to help someone write it — not to reject what they typed.
 */
export function RecipeWorkshop({ recipes }: { recipes: HouseholdRecipe[] }) {
  const t = useTranslations("recipes");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const [pending, start] = useTransition();

  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<IngredientMatch[] | null>(null);

  const set = (field: keyof Draft) => (value: string) =>
    setDraft((current) => ({ ...current, [field]: value }));

  function save() {
    setError(null);
    const body = {
      title: draft.title.trim(),
      servings: draft.servings ? Number(draft.servings) : null,
      lines: draft.lines.split("\n").filter((line) => line.trim()),
      instructions: draft.instructions.trim() || null,
      source_url: draft.source_url.trim() || null,
    };
    start(async () => {
      try {
        if (draft.id) await apiPut(`/recipes/${draft.id}`, body);
        else await apiPost("/recipes", body);
        setDraft(EMPTY);
        setMatches(null);
        setQuery("");
        router.refresh();
      } catch (cause) {
        setError(displayMessage(cause, tCommon));
      }
    });
  }

  function remove(id: string) {
    setError(null);
    start(async () => {
      try {
        await apiDelete(`/recipes/${id}`);
        if (draft.id === id) setDraft(EMPTY);
        router.refresh();
      } catch (cause) {
        setError(displayMessage(cause, tCommon));
      }
    });
  }

  function look() {
    if (!query.trim()) return;
    start(async () => {
      try {
        setMatches(
          await apiGet<IngredientMatch[]>(`/recipes/ingredients?q=${encodeURIComponent(query)}`),
        );
      } catch {
        setMatches([]);
      }
    });
  }

  return (
    <div className="flex flex-col gap-9">
      <section className="flex flex-col gap-4 rounded-card border border-border bg-surface-raised p-5">
        <h2 className="text-[17px] font-semibold text-ink">
          {draft.id ? t("editHeading") : t("writeHeading")}
        </h2>

        <Field
          label={t("titleLabel")}
          placeholder={t("titlePlaceholder")}
          value={draft.title}
          onChange={(event) => set("title")(event.target.value)}
        />

        <Field
          label={t("servingsLabel")}
          hint={t("servingsHint")}
          type="number"
          min={1}
          max={50}
          value={draft.servings}
          onChange={(event) => set("servings")(event.target.value)}
        />

        <div className="flex flex-col gap-1.5">
          <label htmlFor="recipe-lines" className="text-sm font-medium text-ink">
            {t("linesLabel")}
          </label>
          <textarea
            id="recipe-lines"
            rows={5}
            className={TEXTAREA}
            placeholder={t("linesPlaceholder")}
            value={draft.lines}
            onChange={(event) => set("lines")(event.target.value)}
          />
          <p className="text-xs text-ink-muted">{t("linesHint")}</p>
        </div>

        {/* Helping someone write a line the referential knows, rather than
            refusing the one they wrote. */}
        <div className="flex flex-col gap-2 rounded-control bg-surface-sunken px-3 py-2.5">
          <div className="flex flex-wrap items-end gap-2">
            <Field
              label={t("searchLabel")}
              placeholder={t("searchPlaceholder")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              wrapperClassName="flex-1 min-w-[12rem]"
            />
            <Button size="md" disabled={pending || !query.trim()} onClick={look}>
              {t("search")}
            </Button>
          </div>
          {matches !== null &&
            (matches.length === 0 ? (
              <p className="text-xs text-ink-muted">{t("searchEmpty")}</p>
            ) : (
              <ul className="flex flex-wrap gap-1.5">
                {matches.map((match) => (
                  <li key={match.ingredient_id}>
                    <button
                      type="button"
                      onClick={() =>
                        setDraft((current) => ({
                          ...current,
                          lines: `${current.lines}${current.lines.trim() ? "\n" : ""}${match.name.toLowerCase()}`,
                        }))
                      }
                      className={cx(
                        "rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-ink",
                        "hover:bg-surface-sunken focus-visible:outline-2 focus-visible:outline-accent",
                      )}
                    >
                      + {match.name}
                    </button>
                  </li>
                ))}
              </ul>
            ))}
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="recipe-instructions" className="text-sm font-medium text-ink">
            {t("instructionsLabel")}
          </label>
          <textarea
            id="recipe-instructions"
            rows={4}
            className={TEXTAREA}
            placeholder={t("instructionsPlaceholder")}
            value={draft.instructions}
            onChange={(event) => set("instructions")(event.target.value)}
          />
          <p className="text-xs text-ink-muted">{t("instructionsHint")}</p>
        </div>

        <Field
          label={t("sourceLabel")}
          hint={t("sourceHint")}
          placeholder="https://…"
          value={draft.source_url}
          onChange={(event) => set("source_url")(event.target.value)}
        />

        {error && <p className="text-sm text-danger">{error}</p>}

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" disabled={pending || !draft.title.trim()} onClick={save}>
            {draft.id ? t("saveEdit") : t("save")}
          </Button>
          {draft.id && (
            <Button variant="ghost" disabled={pending} onClick={() => setDraft(EMPTY)}>
              {tCommon("cancel")}
            </Button>
          )}
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-[17px] font-semibold text-ink">{t("mineHeading")}</h2>

        {recipes.length === 0 ? (
          <p className="text-sm text-ink-muted">{t("mineEmpty")}</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {recipes.map((recipe) => {
              const unknown = recipe.lines.filter(
                (line) => !line.is_structural && line.ingredient_id === null,
              );
              return (
                <li
                  key={recipe.id}
                  className="rounded-card border border-border bg-surface-raised px-[18px] py-[15px]"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-3">
                    <p className="text-[15px] font-semibold text-ink [overflow-wrap:anywhere]">
                      {recipe.title}
                    </p>
                    <span className="rounded-full bg-surface-sunken px-2.5 py-1 text-[11.5px] text-ink-body">
                      {t(`state.${recipe.state}` as "state.private")}
                    </span>
                  </div>

                  {recipe.servings_raw && (
                    <p className="mt-0.5 text-[13px] text-ink-muted">{recipe.servings_raw}</p>
                  )}

                  {/* What the recipe can and cannot do, said where it is
                      written rather than discovered in a week. */}
                  {unknown.length > 0 ? (
                    <p className="mt-2 text-[13px] leading-[1.5] text-ink-body">
                      {t("unknownLines", {
                        lines: unknown.map((line) => line.raw).join(", "),
                      })}
                    </p>
                  ) : (
                    recipe.lines.length > 0 && (
                      <p className="mt-2 text-[13px] leading-[1.5] text-ink-muted">
                        {recipe.allergens_verified ? t("verified") : t("unverified")}
                      </p>
                    )
                  )}

                  {recipe.state === "rejected" && recipe.rejected_reason && (
                    <p className="mt-2 text-[13px] leading-[1.5] text-ink-body">
                      {t(`rejected.${recipe.rejected_reason}` as "rejected.not_a_meal")}
                    </p>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button size="sm" disabled={pending} onClick={() => setDraft(toDraft(recipe))}>
                      {t("edit")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={pending}
                      onClick={() => remove(recipe.id)}
                    >
                      {t("delete")}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
