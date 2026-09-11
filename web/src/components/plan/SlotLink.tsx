"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { slotHref, type SlotKey } from "@/lib/plan";

/**
 * Opens a meal's panel without asking the server anything.
 *
 * It was a `<Link>`, and in the App Router a link to the same page with another
 * query string is a server navigation: the week and everything around it —
 * seven API calls — were fetched again before the panel could open, for a
 * panel whose dishes were already on screen. `history.pushState` changes the
 * address and nothing else; `SlotPanelHost` reads it back.
 *
 * Still a real anchor with a real href, so a middle click, a new tab or a
 * copied link reach the same meal through the server, as they always did.
 */
export function SlotLink({
  week,
  panelKey,
  className,
  children,
}: {
  week: string;
  panelKey: SlotKey;
  className?: string;
  children: ReactNode;
}) {
  // `next/navigation`, not the locale-aware wrapper: this one keeps the locale
  // prefix, which is what the address bar needs.
  const pathname = usePathname();
  const href = slotHref(pathname, week, panelKey);

  return (
    <a
      href={href}
      className={className}
      onClick={(event) => {
        // Anything but a plain click keeps the browser's own behaviour.
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
          return;
        }
        event.preventDefault();
        window.history.pushState(null, "", href);
      }}
    >
      {children}
    </a>
  );
}
