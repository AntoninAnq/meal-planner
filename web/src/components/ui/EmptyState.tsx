import type { ReactNode } from "react";

import { cx } from "@/lib/cx";

/** Shown where content would be, never as an error.
 *
 * An empty week is the normal state of a Monday morning, not a failure, and
 * `action` is what makes the difference between an explanation and a dead
 * end. */
export function EmptyState({
  title,
  body,
  action,
  className,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "flex flex-col items-center gap-3 rounded-card border border-dashed",
        "border-border px-6 py-10 text-center",
        className,
      )}
    >
      <p className="font-medium text-ink">{title}</p>
      {body && <p className="max-w-prose text-sm text-ink-muted">{body}</p>}
      {action}
    </div>
  );
}
