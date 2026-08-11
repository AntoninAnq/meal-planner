import { cx } from "@/lib/cx";

/** An indeterminate indicator, and deliberately only that.
 *
 * docs/UX-V0.md §7 forbids any fake progress: a bar that advances on its own
 * and then stops at 90% is worse than no bar. There is nothing real to
 * measure — the model returns in one block — so nothing here pretends to. */
export function Spinner({ className, label }: { className?: string; label: string }) {
  return (
    <span
      role="status"
      aria-label={label}
      className={cx(
        "inline-block size-4 animate-spin rounded-full border-2",
        "border-current border-t-transparent",
        className,
      )}
    />
  );
}
