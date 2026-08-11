import { FlatCompat } from "@eslint/eslintrc";
import tseslint from "typescript-eslint";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

export default tseslint.config(
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    // The rule the component library rests on (docs/ARCHITECTURE.md §12.3).
    //
    // `components/ui/` knows nothing about meals. The day a `Button` knows
    // what a `LifeStage` is, the library is dead — and it always starts with
    // one innocent import. A rule nobody enforces does not survive six
    // screens, so it is checked here rather than in a review.
    files: ["src/components/ui/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/lib/api", "@/lib/api/*", "**/lib/api", "**/lib/api/*"],
              message:
                "components/ui/ must not know the domain. Move the component to components/<feature>/ instead.",
            },
          ],
        },
      ],
    },
  },
);
