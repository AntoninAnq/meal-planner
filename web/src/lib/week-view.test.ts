import { describe, expect, it } from "vitest";

import { resolveView, VIEW_COOKIE, viewCookie } from "@/lib/week-view";

describe("resolveView", () => {
  it("hands the decision to the media query when nothing was chosen", () => {
    expect(resolveView(undefined)).toBe("auto");
    expect(resolveView(null)).toBe("auto");
  });

  it("honours an explicit choice", () => {
    expect(resolveView("grid")).toBe("grid");
    expect(resolveView("list")).toBe("list");
  });

  it("falls back to auto rather than throwing on a mangled cookie", () => {
    // A page render must not fail because someone edited a cookie by hand.
    expect(resolveView("GRID")).toBe("auto");
    expect(resolveView("")).toBe("auto");
    expect(resolveView("../../etc/passwd")).toBe("auto");
  });
});

describe("viewCookie", () => {
  it("omits Max-Age so the choice dies with the browser session", () => {
    const cookie = viewCookie("list");
    expect(cookie).toContain(`${VIEW_COOKIE}=list`);
    expect(cookie).not.toMatch(/max-age/i);
    expect(cookie).not.toMatch(/expires/i);
  });
});
