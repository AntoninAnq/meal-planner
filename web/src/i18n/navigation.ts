import { createNavigation } from "next-intl/navigation";

import { routing } from "@/i18n/routing";

/**
 * Locale-aware navigation.
 *
 * Every path is prefixed (`/fr/onboarding`), so `next/navigation`'s own
 * `redirect` and `useRouter` would silently drop the locale and land on a
 * middleware redirect — or on a 404 in the cases the matcher excludes. These
 * wrappers add the prefix.
 */
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
