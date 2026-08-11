"use client";

import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { useId } from "react";

import { cx } from "@/lib/cx";

const CONTROL =
  "h-10 w-full rounded-control border border-border bg-surface-raised px-3 text-sm " +
  "text-ink placeholder:text-ink-faint focus:border-border-strong " +
  "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent " +
  "disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-faint";

function Wrapper({
  id,
  label,
  hint,
  error,
  className,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cx("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {/* The hint is described-by rather than a sibling paragraph so a screen
          reader reads it with the field, not after the whole form. */}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-ink-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

type FieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  label: string;
  hint?: string;
  error?: string;
  wrapperClassName?: string;
};

export function Field({
  label,
  hint,
  error,
  className,
  wrapperClassName,
  ...rest
}: FieldProps) {
  const id = useId();
  return (
    <Wrapper id={id} label={label} hint={hint} error={error} className={wrapperClassName}>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={cx(CONTROL, error && "border-danger", className)}
        {...rest}
      />
    </Wrapper>
  );
}

type SelectFieldProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> & {
  label: string;
  hint?: string;
  error?: string;
  wrapperClassName?: string;
  children: ReactNode;
};

export function SelectField({
  label,
  hint,
  error,
  className,
  wrapperClassName,
  children,
  ...rest
}: SelectFieldProps) {
  const id = useId();
  return (
    <Wrapper id={id} label={label} hint={hint} error={error} className={wrapperClassName}>
      <select
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={cx(CONTROL, error && "border-danger", className)}
        {...rest}
      >
        {children}
      </select>
    </Wrapper>
  );
}
