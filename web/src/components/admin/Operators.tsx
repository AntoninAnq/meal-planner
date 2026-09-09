"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Field, SelectField } from "@/components/ui/Field";
import { apiDelete, apiPost } from "@/lib/api/client";
import { ApiError } from "@/lib/api/error";
import type { Operator, OperatorLevel } from "@/lib/api/types";

const LEVELS: OperatorLevel[] = ["contributor", "owner"];

/** The refusals this screen produces in normal use, mapped to a sentence
 * somebody can act on.
 *
 * `displayMessage` keeps the API's own English wording everywhere else, and
 * that rule is right: those messages reach a developer far more often than a
 * person. These three are the exception for the same reason the quota is —
 * they are what happens when a code was mistyped or when the instance is down
 * to one owner, which is to say every week rather than never.
 */
function refusal(cause: unknown): string | null {
  if (!(cause instanceof ApiError)) return null;
  switch (cause.status) {
    case 404:
      return "unknownCode";
    case 409:
      return "conflict";
    case 422:
      return "malformedCode";
    default:
      return null;
  }
}

/**
 * Who may operate the instance, and the one action that is not a catalogue
 * action.
 *
 * Granting is asked for by support code, never by email: none is stored
 * (§11.7). The person signs in with Google, reads the code in their own
 * settings screen, and sends it over. The right then lands on an identity
 * Google has already verified, rather than on an address somebody typed.
 *
 * A contributor sees this list and no buttons. That is not the guard — the API
 * refuses them either way — it is honesty about what they can do, so nobody
 * presses something that will only answer 403.
 */
export function Operators({
  initial,
  me,
}: {
  initial: Operator[];
  me: Operator;
}) {
  const t = useTranslations("operators");
  const [operators, setOperators] = useState(initial);
  const [code, setCode] = useState("");
  const [level, setLevel] = useState<OperatorLevel>("contributor");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const owner = me.level === "owner";

  async function grant(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const granted = await apiPost<Operator>("/admin/operators", {
        support_code: code,
        level,
      });
      // Re-granting an existing operator is a correction, not a second row.
      setOperators((rest) => [
        ...rest.filter((one) => one.auth_subject !== granted.auth_subject),
        granted,
      ]);
      setCode("");
    } catch (cause) {
      setError(refusal(cause) ?? "failed");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(subject: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiDelete(`/admin/operators/${encodeURIComponent(subject)}`);
      setOperators((rest) => rest.filter((one) => one.auth_subject !== subject));
    } catch (cause) {
      setError(refusal(cause) ?? "failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <ul className="flex flex-col gap-2">
        {operators.map((one) => (
          <li
            key={one.auth_subject}
            className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface-raised px-4 py-3"
          >
            <div className="flex flex-col gap-0.5">
              <span className="flex items-baseline gap-2">
                <span className="font-mono text-sm text-ink">
                  {one.support_code ?? t("noCode")}
                </span>
                {one.auth_subject === me.auth_subject && (
                  <span className="text-xs text-ink-muted">{t("you")}</span>
                )}
              </span>
              <span className="text-xs text-ink-muted">
                {t(`level.${one.level}`)} · {t("since", { date: new Date(one.granted_at) })}
              </span>
            </div>

            {/* Never on your own row: an owner removing themselves is a lockout
                the server can only refuse when they are the last one. */}
            {owner && one.auth_subject !== me.auth_subject && (
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => revoke(one.auth_subject)}>
                {t("revoke")}
              </Button>
            )}
          </li>
        ))}
      </ul>

      {owner ? (
        <form onSubmit={grant} className="flex flex-col gap-3 rounded-card border border-border bg-surface-sunken px-4 py-4">
          <div>
            <h2 className="font-semibold">{t("grantHeading")}</h2>
            <p className="mt-1 text-sm leading-[1.5] text-ink-muted text-pretty">
              {t("grantIntro")}
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <Field
              label={t("codeLabel")}
              hint={t("codeHint")}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="335C-58F8"
              autoComplete="off"
              spellCheck={false}
              className="font-mono uppercase"
              wrapperClassName="min-w-[12rem] flex-1"
            />
            <SelectField
              label={t("levelLabel")}
              value={level}
              onChange={(event) => setLevel(event.target.value as OperatorLevel)}
              wrapperClassName="min-w-[10rem]"
            >
              {LEVELS.map((one) => (
                <option key={one} value={one}>
                  {t(`level.${one}`)}
                </option>
              ))}
            </SelectField>
            <Button type="submit" variant="primary" disabled={busy || code.trim() === ""}>
              {t("grant")}
            </Button>
          </div>
        </form>
      ) : (
        <p className="text-sm text-ink-muted">{t("contributorNote")}</p>
      )}

      {error && (
        <p role="alert" className="text-sm text-danger">
          {t(`error.${error}`)}
        </p>
      )}
    </div>
  );
}
