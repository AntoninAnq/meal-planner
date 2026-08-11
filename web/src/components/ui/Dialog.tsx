"use client";

import type { ReactNode } from "react";
import { useEffect, useRef } from "react";

import { cx } from "@/lib/cx";

/** The native `<dialog>`, and nothing on top of it.
 *
 * `showModal()` already gives the focus trap, Escape, `aria-modal` and inert
 * background that a component library would be installed for. The only things
 * it does not give are backdrop-click-to-close and a body scroll lock, both
 * of which are a few lines below.
 *
 * `open` is meant to be derived from the URL rather than from local state, so
 * the back button closes the panel and a reload reopens it on the same slot
 * (docs/UX-V0.md §14).
 */
export function Dialog({
  open,
  onClose,
  title,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // showModal() throws on an already-open dialog, and close() on a closed
    // one fires a spurious `close` event.
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-label={title}
      // Fires on Escape and on close() alike, so the URL and the element can
      // never disagree about whether the panel is open.
      onClose={onClose}
      onClick={(event) => {
        // The backdrop is part of the dialog element itself: a click landing
        // on the element rather than on its content came from outside.
        if (event.target === ref.current) onClose();
      }}
      className={cx(
        "m-0 ml-auto h-dvh max-h-none w-full max-w-md border-l border-border",
        "bg-surface p-0 text-ink backdrop:bg-ink/30",
        "sm:h-dvh",
        className,
      )}
    >
      <div className="flex h-full flex-col overflow-y-auto">{children}</div>
    </dialog>
  );
}
