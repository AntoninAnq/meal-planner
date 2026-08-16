import { describe, expect, it } from "vitest";

import { playfulIndex, SHOWS_PROGRESS, waitPhase } from "@/lib/waiting";

const EXPECTED = 30_000;

describe("waitPhase", () => {
  it("stays light for the announced duration", () => {
    expect(waitPhase(0, EXPECTED)).toBe("playful");
    expect(waitPhase(EXPECTED, EXPECTED)).toBe("playful");
    expect(waitPhase(EXPECTED * 2 - 1, EXPECTED)).toBe("playful");
  });

  it("drops the joke past twice the expected time", () => {
    // A funny message on the ninetieth second, while the model is stuck, is
    // humiliating.
    expect(waitPhase(EXPECTED * 2, EXPECTED)).toBe("slow");
  });

  it("gives up past three times it", () => {
    expect(waitPhase(EXPECTED * 3, EXPECTED)).toBe("stalled");
  });

  it("scales with the configured duration rather than a constant", () => {
    // 182 s measured on the local 8B: what is "slow" on the cloud model is
    // still perfectly normal here.
    const local = 180_000;
    expect(waitPhase(120_000, local)).toBe("playful");
    expect(waitPhase(120_000, EXPECTED)).toBe("stalled");
  });
});

describe("playfulIndex", () => {
  it("advances on a fixed cadence and wraps", () => {
    expect(playfulIndex(0, 3)).toBe(0);
    expect(playfulIndex(6_000, 3)).toBe(1);
    expect(playfulIndex(12_000, 3)).toBe(2);
    expect(playfulIndex(18_000, 3)).toBe(0);
  });

  it("never divides by zero when a locale has no playful messages", () => {
    expect(playfulIndex(12_000, 0)).toBe(0);
  });
});

it("never claims progress", () => {
  // A bar that advances on its own and then sits at 90% is worse than no bar,
  // and there is nothing real to measure: the model returns in one block.
  expect(SHOWS_PROGRESS).toBe(false);
});
