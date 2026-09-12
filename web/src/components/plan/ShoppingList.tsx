"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useRouter } from "@/i18n/navigation";
import { apiGet } from "@/lib/api/client";
import type { MealType, ShoppingList as ShoppingListData } from "@/lib/api/types";
import { cx } from "@/lib/cx";
import { weekDates } from "@/lib/week";

const MEALS: MealType[] = ["lunch", "dinner"];

/**
 * The list, and the trip to the shops it is for.
 *
 * Entirely a read: the selection lives in this component and in the request,
 * never in a table. It is a decision about ONE trip, and re-opening the drawer
 * tomorrow should start from what is left rather than from what was ticked last
 * Tuesday.
 *
 * The output is text on a clipboard, not a PDF and not a print sheet. It ends
 * up in a message or a note, where neither bold nor columns survive.
 */
export function ShoppingList({
  open,
  weekStart,
  today,
  /** `"3-dinner"` for every meal of this week that actually holds a dish. The
   * grid below draws nothing at all where there is none: a meal with no dish
   * has no state, exactly as in the week grid. */
  plannedSlots,
}: {
  open: boolean;
  weekStart: string;
  today: string;
  plannedSlots: string[];
}) {
  const t = useTranslations("shoppingList");
  const tMeal = useTranslations("mealType");
  const tDay = useTranslations("settings.day");
  const format = useFormatter();
  const locale = useLocale();
  const router = useRouter();

  const planned = useMemo(() => new Set(plannedSlots), [plannedSlots]);
  const dates = useMemo(() => weekDates(weekStart), [weekStart]);

  // Everything left from today on. You shop for what is coming — and a past
  // meal stays tickable, because wanting yesterday's list is a real thing.
  const initial = useCallback(
    () => new Set(plannedSlots.filter((key) => dates[Number(key.split("-")[0])] >= today)),
    [plannedSlots, dates, today],
  );

  const [chosen, setChosen] = useState<Set<string>>(initial);
  const [list, setList] = useState<ShoppingListData | null>(null);
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (open) setChosen(initial());
  }, [open, initial]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const query = [...chosen].map((key) => `slot=${key}`).join("&");
    apiGet<ShoppingListData | null>(
      `/shopping-list?week_start=${weekStart}${query ? `&${query}` : ""}`,
      controller.signal,
    )
      .then(setList)
      .catch(() => setList(null));
    return () => controller.abort();
  }, [open, weekStart, chosen]);

  function close() {
    router.push({ pathname: "/", query: { week: weekStart } });
  }

  function toggle(key: string) {
    setCopied(false);
    setChosen((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  const all = chosen.size === planned.size;

  const day = (date: string) => new Date(`${date}T12:00:00Z`);
  const long = (date: string) =>
    format.dateTime(day(date), { day: "numeric", month: "long", year: "numeric" });

  const sectionLabel = (section: ShoppingListData["sections"][number]) =>
    locale === "en" ? (section.label_en ?? section.label) : section.label;

  const unscaledLine = (recipe: ShoppingListData["unscaled"][number]) =>
    recipe.servings_raw
      ? t("unscaledAs", { title: recipe.title, servings: recipe.servings_raw })
      : t("unscaledUnknown", { title: recipe.title });

  /**
   * Plain text, because that is where it is going.
   *
   * Sections in capitals, a blank line between them, dashes for items, an em
   * dash between a name and its quantity, and NOTHING after a name whose
   * quantity is missing — on screen "quantité non lue" is information, in a
   * message it is noise.
   */
  function asText(data: ShoppingListData): string {
    const first = [...chosen].map((key) => dates[Number(key.split("-")[0])]).sort();
    const range =
      first.length > 1
        ? `${format.dateTime(day(first[0]), { day: "numeric", month: "long" })} – ${format.dateTime(day(first[first.length - 1]), { day: "numeric", month: "long" })}`
        : long(first[0] ?? weekStart);

    const blocks: string[] = [t("textHeading", { range, meals: data.meals })];

    for (const section of data.sections) {
      blocks.push(
        [
          sectionLabel(section).toLocaleUpperCase(locale),
          ...section.lines.map((line) =>
            line.amount ? `- ${line.name} — ${line.amount}` : `- ${line.name}`,
          ),
        ].join("\n"),
      );
    }

    if (data.pantry.length > 0) {
      blocks.push(`${t("textPantry")}\n${data.pantry.join(", ")}.`);
    }
    if (data.unparsed.length > 0) {
      blocks.push(
        [t("textUnparsed"), ...data.unparsed.map((raw) => `- ${raw}`)].join("\n"),
      );
    }
    // What the quantities are travels with the list rather than staying on the
    // screen it was copied from: adjusted to the table, and which recipes could
    // not be — those are the lines worth checking before buying.
    if (data.scaled) blocks.push(t("textScaled"));
    if (data.unscaled.length > 0) {
      blocks.push(
        [t("textUnscaled"), ...data.unscaled.map((recipe) => `- ${unscaledLine(recipe)}`)].join(
          "\n",
        ),
      );
    }

    return blocks.join("\n\n");
  }

  async function copy() {
    if (!list) return;
    const text = asText(list);
    setFailed(false);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // `navigator.clipboard` is undefined outside a secure context, and
      // refused without a user gesture in some browsers. The old mechanism
      // still works in both.
      try {
        const area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.append(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      } catch {
        setFailed(true);
        return;
      }
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Dialog open={open} onClose={close} title={t("title")}>
      <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div>
          <h2 className="text-lg leading-[1.2] font-semibold">{t("title")}</h2>
          <p className="mt-1 text-[13px] text-ink-muted">
            {t("week", { date: long(weekStart) })}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={close}>
          {t("close")}
        </Button>
      </header>

      {/* The week in miniature rather than a row of days: a day holds a lunch
          AND a dinner, and "mardi midi je mange au bureau" has to be sayable.
          Same seven columns and same two rows as the grid, so nobody has to
          learn a second shape — they recognise their own week, in small. */}
      <section className="border-b border-border px-[22px] py-[18px]">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-[13px] font-medium text-ink-body">{t("whichMeals")}</h3>
          <button
            type="button"
            onClick={() => setChosen(all ? new Set() : new Set(planned))}
            className="text-[12.5px] text-ink-muted underline underline-offset-2 hover:text-ink"
          >
            {all ? t("uncheckAll") : t("checkAll")}
          </button>
        </div>

        <div className="mt-3 grid grid-cols-[38px_repeat(7,minmax(0,1fr))] items-center gap-1 sm:gap-[5px]">
          <div />
          {dates.map((date, dayOfWeek) => (
            <div
              key={date}
              className="text-center text-[11.5px] font-semibold text-ink-muted"
            >
              {tDay(String(dayOfWeek) as "0").slice(0, 1)}{" "}
              {format.dateTime(day(date), { day: "numeric" })}
            </div>
          ))}

          {MEALS.map((mealType) => (
            <Fragment key={mealType}>
              <div className="text-[10.5px] font-semibold tracking-[0.06em] text-ink-muted uppercase">
                {tMeal(mealType)}
              </div>
              {dates.map((date, dayOfWeek) => {
                const key = `${dayOfWeek}-${mealType}`;
                // Nothing at all where there is no dish. Same rule as the grid:
                // a meal with no dish has no state, so it has no box either.
                if (!planned.has(key)) return <div key={key} className="h-11 sm:h-[30px]" />;
                const ticked = chosen.has(key);
                return (
                  <label
                    key={key}
                    className={cx(
                      "flex h-11 cursor-pointer items-center justify-center rounded-[6px] border sm:h-[30px]",
                      "transition-colors focus-within:outline-2 focus-within:outline-offset-2",
                      "focus-within:outline-accent",
                      ticked
                        ? "border-accent bg-accent"
                        : "border-border bg-surface-raised hover:bg-surface-sunken",
                    )}
                  >
                    {/* A real checkbox, visually replaced. Never a div with an
                        onClick: this is the only control on the screen. */}
                    <input
                      type="checkbox"
                      checked={ticked}
                      onChange={() => toggle(key)}
                      aria-label={t("mealLabel", {
                        day: format.dateTime(day(date), { weekday: "long", day: "numeric" }),
                        meal: tMeal(mealType),
                      })}
                      className="sr-only"
                    />
                    {/* The tick, not the colour, is what separates checked from
                        unchecked: the state must not rest on green alone. */}
                    <span aria-hidden className="text-[13px] font-semibold text-accent-ink">
                      {ticked ? "✓" : ""}
                    </span>
                  </label>
                );
              })}
            </Fragment>
          ))}
        </div>

        {list && (
          // The second sentence explains the holes. Without it a half-empty
          // grid looks like a failed load.
          <p className="mt-3 text-[12.5px] leading-[1.5] text-ink-muted">
            {t("selection", { meals: list.meals, days: list.days })}
          </p>
        )}
        {list?.missing_recipe && (
          <p className="mt-1.5 text-[12.5px] leading-[1.5] text-ink-muted">
            {t("missingRecipe")}
          </p>
        )}
      </section>

      <section className="flex flex-1 flex-col px-[22px] py-[18px]">
        {chosen.size === 0 || list === null ? (
          <p className="text-sm text-ink-muted">{t("empty")}</p>
        ) : (
          <>
            <h3 className="text-xs font-semibold tracking-[0.06em] text-ink-muted uppercase">
              {t("toBuy")}
            </h3>

            {list.sections.map((section) => (
              <div key={section.code}>
                <h4 className="mt-4 text-[13px] font-semibold text-ink-body">
                  {sectionLabel(section)}
                </h4>
                <ul>
                  {section.lines.map((line) => (
                    <li
                      key={line.name}
                      className="flex items-baseline justify-between gap-4 border-b border-border py-[7px] text-sm"
                    >
                      <span className="min-w-0 [overflow-wrap:anywhere]">{line.name}</span>
                      {/* An absence of information has to weigh less than a
                          real quantity and stay legible: the scale does that
                          job — `ink-body` for an amount, `ink-muted` and
                          italic for its absence. Not `ink-faint`, which would
                          fall to 3.1:1. */}
                      {line.amount ? (
                        <span className="flex-none text-ink-body">{line.amount}</span>
                      ) : (
                        <span className="flex-none text-ink-muted italic">
                          {t("noQuantity")}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}

            {list.pantry.length > 0 && (
              <div className="mt-[22px] border-t border-border pt-[18px]">
                <h3 className="text-xs font-semibold tracking-[0.06em] text-ink-muted uppercase">
                  {t("pantry")}
                </h3>
                {/* One sentence, no quantities: nobody checks whether they have
                    200 g of salt, they check whether there is salt. */}
                <p className="mt-1.5 text-[13px] leading-[1.5] text-ink-body">
                  {list.pantry.join(", ")}.
                </p>
              </div>
            )}

            {list.unparsed.length > 0 && (
              <div className="mt-[22px] border-t border-border pt-[18px]">
                <h3 className="text-xs font-semibold tracking-[0.06em] text-ink-muted uppercase">
                  {t("unparsed", { count: list.unparsed.length })}
                </h3>
                {/* This section tells the truth about the data. It shrinks as
                    the referential fills, which is the right incentive. */}
                <p className="mt-1.5 text-[13px] leading-[1.5] text-ink-body">
                  {t("unparsedHelp")}
                </p>
                <ul className="mt-2">
                  {list.unparsed.map((raw) => (
                    <li
                      key={raw}
                      className="border-b border-border py-1.5 text-[13.5px] text-ink-body"
                    >
                      {raw}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Said per recipe rather than once for the whole list: most
                quantities are adjusted to the table now, and the ones that are
                not are the ones to check. Not to be dropped for space. */}
            {list.scaled && (
              <p className="mt-[18px] text-[12.5px] leading-[1.6] text-ink-muted">
                {t("scaledNote")}
              </p>
            )}
            {list.unscaled.length > 0 && (
              <div className="mt-[18px]">
                <p className="text-[12.5px] font-medium text-ink-body">{t("unscaledHeading")}</p>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {list.unscaled.map((recipe, index) => (
                    <li
                      key={`${index}-${recipe.title}`}
                      className="text-[12.5px] leading-[1.5] text-ink-muted"
                    >
                      {unscaledLine(recipe)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-[18px] flex flex-wrap items-center gap-3">
              <Button variant="primary" className="h-11 px-5" onClick={copy}>
                {copied ? t("copied") : t("copy")}
              </Button>
              <span className="text-[13px] text-ink-muted">{t("copyHint")}</span>
            </div>
            {/* The label changing is a confirmation only for those who see it. */}
            <p aria-live="polite" className="mt-1.5 text-[13px] text-ink-muted">
              {copied ? t("copied") : ""}
              {failed ? t("copyFailed") : ""}
            </p>
          </>
        )}
      </section>
    </Dialog>
  );
}
