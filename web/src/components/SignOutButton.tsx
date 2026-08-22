"use client";

import { useTranslations } from "next-intl";
import { useState, useTransition } from "react";

import { useRouter } from "@/i18n/navigation";
import { apiPost } from "@/lib/api/client";

/**
 * Signing out has to be a POST, and that is why this is a component rather
 * than a link.
 *
 * A `GET /auth/logout` is a URL any page can embed — an image tag on a forum is
 * enough to sign someone out. Harmless as pranks go, and still the reason the
 * endpoint refuses anything but POST.
 *
 * `router.refresh()` rather than a hard reload: the 204 carries the expiring
 * cookie, so by the time this runs the browser has already dropped it, and the
 * server re-renders the page as the sign-in screen. The plan stays in place
 * until then, which is what makes an accidental click cost nothing.
 *
 * A failure is deliberately silent in the interface. The cookie either went or
 * it did not; the honest recovery is to leave the household where it is rather
 * than show an error about a thing it did not ask for.
 */
export function SignOutButton() {
  const t = useTranslations("account");
  const router = useRouter();
  const [pending, start] = useTransition();
  const [leaving, setLeaving] = useState(false);

  return (
    <button
      type="button"
      disabled={pending || leaving}
      onClick={() => {
        setLeaving(true);
        apiPost("/auth/logout")
          .then(() => start(() => router.refresh()))
          .finally(() => setLeaving(false));
      }}
      className="rounded-control px-2 py-1 text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink disabled:opacity-50"
    >
      {t("signOut")}
    </button>
  );
}
