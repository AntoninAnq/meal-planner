import type { ReactNode } from "react";

import { cx } from "@/lib/cx";

/** A raised surface. No padding scale of its own — the caller sizes it,
 * because a slot card and a settings panel have nothing in common but the
 * border. */
export function Card({
  as: Tag = "div",
  className,
  children,
}: {
  as?: "div" | "section" | "article" | "li";
  className?: string;
  children: ReactNode;
}) {
  return (
    <Tag
      className={cx(
        "rounded-card border border-border bg-surface-raised",
        className,
      )}
    >
      {children}
    </Tag>
  );
}
