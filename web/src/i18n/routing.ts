import { defineRouting } from "next-intl/routing";

/**
 * The product ships in French first but is i18n-ready from phase 0: no
 * displayed string is ever hardcoded (docs/ARCHITECTURE.md §12.1).
 *
 * Note that an English edition would need a distinct recipe catalogue, not just
 * translated labels — and that France-specific concepts (the 4pm `snack` above
 * all) are optional modules, never wired into the core.
 */
export const routing = defineRouting({
  locales: ["fr", "en"],
  defaultLocale: "fr",
});
