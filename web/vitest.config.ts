import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    // Vitest does not read tsconfig `paths`, so the alias is restated here.
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    // Only pure functions are tested (docs/ARCHITECTURE.md §13.4). Restricting
    // the glob to `lib/` is the enforcement: a test written against a
    // component simply never runs, which is a louder signal than a review
    // comment.
    include: ["src/lib/**/*.test.ts"],
  },
});
