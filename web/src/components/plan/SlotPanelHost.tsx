"use client";

import { useSearchParams } from "next/navigation";

import { SlotPanel } from "@/components/plan/SlotPanel";
import type { Dish } from "@/lib/api/types";
import { parseSlotKey, slotKey } from "@/lib/plan";
import { weekDates } from "@/lib/week";

/**
 * Which meal's panel is open, read from the address bar on the client.
 *
 * The slot still travels in the URL — the back button closes the panel and a
 * reload reopens it on the same meal — but opening one no longer re-renders
 * the page on the server. The dishes come from the week this page already
 * loaded, and `router.refresh()` after an action is what brings new ones.
 */
export function SlotPanelHost({
  planId,
  weekStart,
  dishesBySlot,
  memberNames,
  locale,
  expectedMs,
}: {
  planId: string | null;
  weekStart: string;
  dishesBySlot: Record<string, Dish[]>;
  memberNames: Record<string, string>;
  locale: string;
  expectedMs: number;
}) {
  // A mistyped key simply leaves it shut.
  const open = parseSlotKey(useSearchParams().get("slot") ?? "");
  if (!open) return null;

  const key = slotKey(open.dayOfWeek, open.mealType);
  return (
    <SlotPanel
      // A title typed in one meal must not follow the reader into the next.
      key={key}
      open
      planId={planId}
      weekStart={weekStart}
      date={weekDates(weekStart)[open.dayOfWeek]}
      dayOfWeek={open.dayOfWeek}
      mealType={open.mealType}
      dishes={dishesBySlot[key] ?? []}
      memberNames={memberNames}
      locale={locale}
      expectedMs={expectedMs}
    />
  );
}
