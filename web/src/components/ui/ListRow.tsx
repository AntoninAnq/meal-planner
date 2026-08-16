import type { ReactNode } from "react";

import { cx } from "@/lib/cx";

/** A row in a short editable list: content on the left, one action on the right.
 *
 * Extracted on its second use — the member list and the allergy list of the
 * onboarding — rather than guessed up front. The settings screen has the same
 * shape three more times.
 */
export function ListRow({
  action,
  className,
  children,
}: {
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <li
      className={cx(
        "flex items-center justify-between gap-3 rounded-control border",
        "border-border bg-surface-raised px-3 py-2 text-sm",
        className,
      )}
    >
      <span className="min-w-0">{children}</span>
      {action}
    </li>
  );
}
