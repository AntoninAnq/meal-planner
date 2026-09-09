"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { apiGet, apiPost, apiPut } from "@/lib/api/client";
import { ApiError } from "@/lib/api/error";
import type { AdminHousehold, AdminHouseholds } from "@/lib/api/types";

/**
 * The households, and the three things an operator does to one.
 *
 * These are the verbs reached for on a bad night — somebody is burning the
 * budget, or should not be here any more — and until now they meant a shell on
 * the production host. What they act on is people, not the catalogue, which is
 * why the whole screen is owner-only down to the reads.
 *
 * **Every action refetches instead of patching the row in place.** That is the
 * opposite of the classifying queue, deliberately: there, the reader's rhythm
 * is the point and the server is not the authority on what has already been
 * shown. Here a wrong number on screen is somebody's account, the actions are
 * rare, and a round trip costs nothing anyone will feel.
 */
export function Households({ initial }: { initial: AdminHouseholds }) {
  const t = useTranslations("households");
  const [data, setData] = useState(initial);
  const [code, setCode] = useState("");
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(searched: string) {
    setBusy(true);
    setError(null);
    try {
      const query = searched.trim() === "" ? "" : `?code=${encodeURIComponent(searched.trim())}`;
      setData(await apiGet<AdminHouseholds>(`/admin/households${query}`));
      setSearching(searched.trim() !== "");
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 422 ? "malformedCode" : "failed");
    } finally {
      setBusy(false);
    }
  }

  async function act(run: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await run();
      await load(searching ? code : "");
    } catch {
      setError("failed");
      setBusy(false);
    }
  }

  function search(event: FormEvent) {
    event.preventDefault();
    void load(code);
  }

  return (
    <div className="flex flex-col gap-5">
      <form onSubmit={search} className="flex flex-wrap items-end gap-3">
        <Field
          label={t("searchLabel")}
          hint={t("searchHint")}
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder="335C-58F8"
          autoComplete="off"
          spellCheck={false}
          className="font-mono uppercase"
          wrapperClassName="min-w-[12rem] flex-1"
        />
        <Button type="submit" disabled={busy}>
          {t("search")}
        </Button>
        {searching && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              setCode("");
              void load("");
            }}
          >
            {t("clearSearch")}
          </Button>
        )}
      </form>

      <p className="text-sm text-ink-muted" aria-live="polite">
        {searching
          ? t("found", { count: data.households.length })
          : t("busiest", { count: data.households.length, hours: data.window_hours })}
      </p>

      <ul className="flex flex-col gap-3">
        {data.households.map((household) => (
          <HouseholdCard
            // The ceiling is part of the key so a card remounts when it
            // changes: the input below holds a draft, and a draft left over
            // from before the write would show a number that is no longer true.
            key={`${household.household_id}:${household.limit_override}`}
            household={household}
            defaultLimit={data.default_limit}
            windowHours={data.window_hours}
            busy={busy}
            act={act}
          />
        ))}
      </ul>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {t(`error.${error}`)}
        </p>
      )}
    </div>
  );
}

function HouseholdCard({
  household,
  defaultLimit,
  windowHours,
  busy,
  act,
}: {
  household: AdminHousehold;
  defaultLimit: number;
  windowHours: number;
  busy: boolean;
  act: (run: () => Promise<unknown>) => Promise<void>;
}) {
  const t = useTranslations("households");
  const [limit, setLimit] = useState(
    household.limit_override === null ? "" : String(household.limit_override),
  );

  const ceiling = household.limit_override ?? defaultLimit;
  const spent = household.calls_in_window;

  function apply(value: number | null) {
    void act(() => apiPut(`/admin/households/${household.household_id}/limit`, { limit: value }));
  }

  return (
    <li className="flex flex-col gap-3 rounded-card border border-border bg-surface-raised px-4 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold text-pretty">{household.name}</h2>
        <span className="font-mono text-sm text-ink-muted">{household.code}</span>
      </div>

      <p className="flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-ink-muted">
        <span>{t("members", { count: household.members })}</span>
        <span>
          {/* Spend against ceiling, on one line: either number alone says
              nothing, and it is the comparison that decides whether to act. */}
          {t("spend", { calls: spent, ceiling, hours: windowHours })}
        </span>
        {household.limit_override === null && <span>{t("onRateCard")}</span>}
      </p>

      <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
        <Field
          label={t("limitLabel")}
          hint={t("limitHint", { defaultLimit })}
          value={limit}
          onChange={(event) => setLimit(event.target.value.replace(/[^0-9]/g, ""))}
          inputMode="numeric"
          placeholder={String(defaultLimit)}
          wrapperClassName="w-32"
        />
        <Button disabled={busy || limit === ""} onClick={() => apply(Number(limit))}>
          {t("applyLimit")}
        </Button>
        {household.limit_override !== null && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              setLimit("");
              apply(null);
            }}
          >
            {t("clearLimit")}
          </Button>
        )}
      </div>

      <ul className="flex flex-col gap-1.5 border-t border-border pt-3">
        {household.subjects.map((subject) => (
          <Access
            key={subject}
            subject={subject}
            busy={busy}
            label={t("cut")}
            onClick={() =>
              void act(() =>
                apiPost(`/admin/households/access/${encodeURIComponent(subject)}/revoke`, {}),
              )
            }
          />
        ))}
        {household.revoked.map((subject) => (
          <Access
            key={subject}
            subject={subject}
            busy={busy}
            revoked={t("revoked")}
            label={t("restore")}
            onClick={() =>
              void act(() =>
                apiPost(`/admin/households/access/${encodeURIComponent(subject)}/restore`, {}),
              )
            }
          />
        ))}
      </ul>
    </li>
  );
}

/** One identity. The subject is shown in full on hover and truncated on screen:
 * it is a twenty-one digit Google identifier, and the only reason to read it is
 * to compare it with another one. */
function Access({
  subject,
  revoked,
  label,
  busy,
  onClick,
}: {
  subject: string;
  revoked?: string;
  label: string;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <li className="flex items-center justify-between gap-2">
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="truncate font-mono text-xs text-ink-muted" title={subject}>
          {subject}
        </span>
        {revoked && <span className="flex-none text-xs text-danger">{revoked}</span>}
      </span>
      <Button variant="ghost" size="sm" disabled={busy} onClick={onClick} className="flex-none">
        {label}
      </Button>
    </li>
  );
}
