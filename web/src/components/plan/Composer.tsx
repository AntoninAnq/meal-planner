"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { apiPost } from "@/lib/api/client";
import { ApiError } from "@/lib/api/error";
import type { InterpretedConstraint } from "@/lib/api/types";

/**
 * Free text, then the reading of it, then the generation.
 *
 * The interpretation is never invisible. When the model reads "tuesday I'm
 * home late" as "no meal on tuesday", the user gets a wrong plan and no way to
 * know why — they can only rephrase blindly. That is the classic failure mode
 * of free text: impressive in a demo, exasperating in use.
 *
 * It also buys two things beyond the UX: the correction happens before the
 * expensive step (one click instead of a regeneration), and the interpretation
 * becomes testable on its own, against frozen text, without generating a plan.
 */
export function Composer({
  hasPlan,
  busy,
  onGenerate,
}: {
  hasPlan: boolean;
  busy: boolean;
  onGenerate: (constraints: InterpretedConstraint[]) => void;
}) {
  const t = useTranslations("composer");
  const tCommon = useTranslations("common");

  const [open, setOpen] = useState(!hasPlan);
  const [text, setText] = useState("");
  const [constraints, setConstraints] = useState<InterpretedConstraint[] | null>(null);
  const [interpreting, setInterpreting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function interpret() {
    setInterpreting(true);
    setError(null);
    try {
      const result = await apiPost<{ constraints: InterpretedConstraint[] }>(
        "/meal-plans/interpret",
        { text: text.trim() },
      );
      setConstraints(result.constraints);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : tCommon("genericError"));
    } finally {
      setInterpreting(false);
    }
  }

  function generate() {
    // Sent STRUCTURED, not flattened to `label: detail`. The reading produced
    // `{kind, label, detail}` and the user just confirmed it; throwing the
    // shape away here is what forced the model to search sixty candidates for
    // "du jambon" instead of letting the pre-filter rank them.
    onGenerate(constraints ?? []);
  }

  // Editing the text invalidates the reading of it: generating against chips
  // that no longer match what is on screen is the one thing this flow exists
  // to prevent.
  function edit(value: string) {
    setText(value);
    if (constraints !== null) setConstraints(null);
  }

  const needsReading = text.trim().length > 0 && constraints === null;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full rounded-card border border-dashed border-border px-4 py-3 text-left text-sm text-ink-muted transition-colors hover:border-border-strong hover:text-ink"
      >
        {t("collapsed")}
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-card border border-border bg-surface-raised p-4">
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">{t("label")}</span>
        <textarea
          rows={3}
          value={text}
          onChange={(event) => edit(event.target.value)}
          placeholder={t("placeholder")}
          disabled={busy}
          className="w-full resize-y rounded-control border border-border bg-surface px-3 py-2 text-sm placeholder:text-ink-faint focus:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
        />
      </label>

      {constraints !== null && (
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium">
            {constraints.length === 0 ? t("understoodNothing") : t("understood")}
          </p>
          <ul className="flex flex-wrap gap-2">
            {constraints.map((constraint, index) => (
              <li
                key={`${constraint.label}-${index}`}
                className="flex items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-sm text-ink"
              >
                <span>
                  {constraint.label}
                  {constraint.detail && (
                    <span className="text-ink-muted"> — {constraint.detail}</span>
                  )}
                </span>
                <button
                  type="button"
                  onClick={() =>
                    setConstraints((current) =>
                      (current ?? []).filter((_, position) => position !== index),
                    )
                  }
                  aria-label={t("dropConstraint", { label: constraint.label })}
                  className="text-ink-faint hover:text-danger"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="flex flex-wrap items-center gap-3">
        {needsReading ? (
          <Button variant="secondary" disabled={interpreting || busy} onClick={interpret}>
            {interpreting && <Spinner label={t("reading")} />}
            {t("read")}
          </Button>
        ) : (
          <Button variant="primary" disabled={busy} onClick={generate}>
            {t("generate")}
          </Button>
        )}
        {hasPlan && !busy && (
          <Button variant="ghost" onClick={() => setOpen(false)}>
            {tCommon("cancel")}
          </Button>
        )}
      </div>
    </div>
  );
}
