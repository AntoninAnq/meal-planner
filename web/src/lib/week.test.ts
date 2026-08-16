import { describe, expect, it } from "vitest";

import { addDays, dayIndexOf, isIsoDate, mondayOf, resolveWeek, weekDates } from "@/lib/week";

describe("mondayOf", () => {
  it("treats monday as the start of the week", () => {
    expect(mondayOf("2026-08-10")).toBe("2026-08-10"); // a monday
    expect(mondayOf("2026-08-11")).toBe("2026-08-10");
    expect(mondayOf("2026-08-16")).toBe("2026-08-10"); // sunday belongs to it
  });

  it("does not shift across a DST boundary", () => {
    // Europe/Paris springs forward on 2026-03-29. Working in UTC on plain
    // strings is what keeps this from landing on the 22nd.
    expect(mondayOf("2026-03-29")).toBe("2026-03-23");
    expect(mondayOf("2026-10-25")).toBe("2026-10-19");
  });
});

describe("addDays", () => {
  it("crosses months and years", () => {
    expect(addDays("2026-08-31", 1)).toBe("2026-09-01");
    expect(addDays("2026-01-01", -1)).toBe("2025-12-31");
    expect(addDays("2024-02-28", 1)).toBe("2024-02-29"); // leap year
  });
});

describe("weekDates", () => {
  it("returns seven consecutive days starting on the given monday", () => {
    expect(weekDates("2026-08-10")).toEqual([
      "2026-08-10",
      "2026-08-11",
      "2026-08-12",
      "2026-08-13",
      "2026-08-14",
      "2026-08-15",
      "2026-08-16",
    ]);
  });
});

describe("isIsoDate", () => {
  it("rejects what looks right but is not a date", () => {
    expect(isIsoDate("2026-02-30")).toBe(false);
    expect(isIsoDate("2026-13-01")).toBe(false);
    expect(isIsoDate("2026-8-10")).toBe(false);
    expect(isIsoDate("")).toBe(false);
  });

  it("accepts a real date", () => {
    expect(isIsoDate("2026-08-10")).toBe(true);
    expect(isIsoDate("2024-02-29")).toBe(true);
  });
});

describe("resolveWeek", () => {
  const today = "2026-08-11";

  it("uses the current week when the parameter is absent", () => {
    expect(resolveWeek(undefined, today)).toBe("2026-08-10");
  });

  it("snaps any day of the requested week to its monday", () => {
    expect(resolveWeek("2026-08-19", today)).toBe("2026-08-17");
  });

  it("falls back rather than erroring on a mistyped URL", () => {
    expect(resolveWeek("next-week", today)).toBe("2026-08-10");
    expect(resolveWeek("2026-02-30", today)).toBe("2026-08-10");
  });

  it("takes the first value of a repeated query parameter", () => {
    expect(resolveWeek(["2026-08-17", "2026-09-07"], today)).toBe("2026-08-17");
  });
});

describe("dayIndexOf", () => {
  it("maps a date to the day_of_week the API uses", () => {
    expect(dayIndexOf("2026-08-10", "2026-08-10")).toBe(0);
    expect(dayIndexOf("2026-08-13", "2026-08-10")).toBe(3);
    expect(dayIndexOf("2026-09-01", "2026-08-10")).toBe(-1);
  });
});
