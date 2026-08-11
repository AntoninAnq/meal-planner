import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cx } from "@/lib/cx";

/** Variants exist to rank actions on a screen, not to decorate them.
 *
 * `danger` is reserved for what destroys something the user cannot recover
 * (deleting a member). Refusing a dish is not dangerous — it is `secondary`. */
type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-control font-medium " +
  "transition-colors disabled:cursor-not-allowed disabled:opacity-50 " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:bg-accent-hover",
  secondary: "bg-surface-raised text-ink border border-border hover:bg-surface-sunken",
  ghost: "text-ink-muted hover:bg-surface-sunken hover:text-ink",
  danger: "bg-danger-soft text-danger border border-danger/30 hover:bg-danger hover:text-accent-ink",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-sm",
  md: "h-10 px-4 text-sm",
};

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  type = "button",
  children,
  ...rest
}: Props) {
  return (
    <button
      // Explicit by default: an unspecified `type` inside a form submits it,
      // which is never what a plain button means.
      type={type}
      className={cx(BASE, VARIANTS[variant], SIZES[size], className)}
      {...rest}
    >
      {children}
    </button>
  );
}
