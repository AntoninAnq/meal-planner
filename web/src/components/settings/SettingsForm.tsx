"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field, SelectField } from "@/components/ui/Field";
import { ListRow } from "@/components/ui/ListRow";
import { apiDelete, apiPatch, apiPost, apiPut } from "@/lib/api/client";
import { ApiError } from "@/lib/api/error";
import {
  ALLERGEN_CODES,
  type AllergenCode,
  type ConstraintSeverity,
  type DietaryConstraint,
  type Household,
  type HouseholdSettings,
  type LifeStage,
  type MealSlot,
  type MealType,
  type Member,
} from "@/lib/api/types";

const LIFE_STAGES: LifeStage[] = ["baby", "young_child", "teen_adult"];
const MEALS: MealType[] = ["lunch", "dinner"];
const DAYS = [0, 1, 2, 3, 4, 5, 6];

/**
 * Screen 6. Everything the onboarding did not ask, plus everything it did.
 *
 * The same objects as the onboarding — members, constraints — so the two
 * screens were written after each other on purpose: the row, the async
 * wrapper and the pickers are shared rather than written twice.
 */
export function SettingsForm({
  household,
  settings,
  members: initialMembers,
  constraints: initialConstraints,
  slots: initialSlots,
}: {
  household: Household;
  settings: HouseholdSettings;
  members: Member[];
  constraints: DietaryConstraint[];
  slots: MealSlot[];
}) {
  const t = useTranslations("settings");
  const tCommon = useTranslations("common");
  const tStage = useTranslations("lifeStage");
  const tMeal = useTranslations("mealType");
  const tAllergen = useTranslations("allergen");

  const [name, setName] = useState(household.name);
  const [members, setMembers] = useState(initialMembers);
  const [constraints, setConstraints] = useState(initialConstraints);
  const [slots, setSlots] = useState(initialSlots);
  const [snacks, setSnacks] = useState(settings.snacks_enabled);

  const [newName, setNewName] = useState("");
  const [newStage, setNewStage] = useState<LifeStage>("teen_adult");
  const [cMember, setCMember] = useState("");
  const [cSeverity, setCSeverity] = useState<ConstraintSeverity>("aversion");
  const [cAllergen, setCAllergen] = useState<AllergenCode>("gluten");
  const [cLabel, setCLabel] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await action();
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : tCommon("genericError"));
    } finally {
      setBusy(false);
    }
  }

  const isAllergy = cSeverity !== "aversion";

  const enabledAt = (day: number, meal: MealType) =>
    slots.some((slot) => slot.day_of_week === day && slot.meal_type === meal && slot.enabled);

  function toggleSlot(day: number, meal: MealType) {
    const next = slots.some((slot) => slot.day_of_week === day && slot.meal_type === meal)
      ? slots.map((slot) =>
          slot.day_of_week === day && slot.meal_type === meal
            ? { ...slot, enabled: !slot.enabled }
            : slot,
        )
      : [...slots, { day_of_week: day, meal_type: meal, enabled: true }];
    setSlots(next);
    run(async () => {
      await apiPut("/household/slots", next);
    });
  }

  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">{t("householdHeading")}</h2>
        <div className="flex items-end gap-2">
          <Field
            label={t("householdName")}
            value={name}
            onChange={(event) => setName(event.target.value)}
            wrapperClassName="flex-1"
          />
          <Button
            disabled={busy || !name.trim() || name === household.name}
            onClick={() => run(async () => void (await apiPatch("/household", { name: name.trim() })))}
          >
            {t("save")}
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">{t("membersHeading")}</h2>
        <ul className="flex flex-col gap-2">
          {members.map((member) => (
            <ListRow
              key={member.id}
              action={
                <div className="flex items-center gap-2">
                  {/* The stage is chosen, never derived: no birth date is
                      collected, so nothing proposes a transition. Crossing
                      baby -> young child widens what is allowed, and only a
                      parent can judge whether this child is ready. */}
                  <select
                    aria-label={t("stageOf", { name: member.display_name })}
                    value={member.life_stage}
                    disabled={busy}
                    onChange={(event) => {
                      const confirmed = event.target.value as LifeStage;
                      setMembers((current) =>
                        current.map((m) =>
                          m.id === member.id ? { ...m, life_stage: confirmed } : m,
                        ),
                      );
                      run(async () => {
                        await apiPost(`/members/${member.id}/life-stage`, { confirmed });
                      });
                    }}
                    className="h-8 rounded-control border border-border bg-surface-raised px-2 text-sm"
                  >
                    {LIFE_STAGES.map((stage) => (
                      <option key={stage} value={stage}>
                        {tStage(stage)}
                      </option>
                    ))}
                  </select>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy || members.length <= 1}
                    onClick={() =>
                      run(async () => {
                        await apiDelete(`/members/${member.id}`);
                        setMembers((current) => current.filter((m) => m.id !== member.id));
                      })
                    }
                  >
                    {tCommon("remove")}
                  </Button>
                </div>
              }
            >
              <strong className="font-medium">{member.display_name}</strong>
            </ListRow>
          ))}
        </ul>

        <div className="flex flex-wrap items-end gap-2">
          <Field
            label={t("newMember")}
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            wrapperClassName="min-w-40 flex-1"
          />
          <SelectField
            label={t("stage")}
            value={newStage}
            onChange={(event) => setNewStage(event.target.value as LifeStage)}
            wrapperClassName="min-w-36"
          >
            {LIFE_STAGES.map((stage) => (
              <option key={stage} value={stage}>
                {tStage(stage)}
              </option>
            ))}
          </SelectField>
          <Button
            disabled={busy || !newName.trim()}
            onClick={() =>
              run(async () => {
                const created = await apiPost<Member>("/members", {
                  display_name: newName.trim(),
                  life_stage: newStage,
                });
                setMembers((current) => [...current, created]);
                setNewName("");
              })
            }
          >
            {tCommon("add")}
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("constraintsHeading")}</h2>
          <p className="text-sm text-ink-muted">{t("constraintsHint")}</p>
        </div>


        <ul className="flex flex-col gap-2">
          {constraints.map((constraint) => (
            <ListRow
              key={constraint.id}
              action={
                <div className="flex items-center gap-2">
                  {/* Refinement goes ONE WAY only: "nobody likes spinach here"
                      -> "actually it is mostly Léo" is natural, the reverse is
                      not — and a per-member aversion argues for a second dish,
                      where a household one just removes the ingredient. */}
                  {constraint.severity === "aversion" && constraint.member_id === null && (
                    <select
                      aria-label={t("attachTo")}
                      defaultValue=""
                      disabled={busy}
                      onChange={(event) => {
                        const memberId = event.target.value;
                        if (!memberId) return;
                        run(async () => {
                          const updated = await apiPatch<DietaryConstraint>(
                            `/household/constraints/${constraint.id}?member_id=${memberId}`,
                          );
                          setConstraints((current) =>
                            current.map((c) => (c.id === updated.id ? updated : c)),
                          );
                        });
                      }}
                      className="h-8 rounded-control border border-border bg-surface-raised px-2 text-sm"
                    >
                      <option value="">{t("attachTo")}</option>
                      {members.map((member) => (
                        <option key={member.id} value={member.id}>
                          {member.display_name}
                        </option>
                      ))}
                    </select>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await apiDelete(`/household/constraints/${constraint.id}`);
                        setConstraints((current) =>
                          current.filter((c) => c.id !== constraint.id),
                        );
                      })
                    }
                  >
                    {tCommon("remove")}
                  </Button>
                </div>
              }
            >
              {t("constraintRow", {
                who: constraint.member_id
                  ? (members.find((m) => m.id === constraint.member_id)?.display_name ?? "?")
                  : t("wholeHousehold"),
                what: constraint.allergen_code
                  ? tAllergen(constraint.allergen_code)
                  : (constraint.label ?? "?"),
                severity: t(`severity.${constraint.severity}`),
              })}
            </ListRow>
          ))}
        </ul>

        <div className="flex flex-wrap items-end gap-2">
          <SelectField
            label={t("severity.label")}
            value={cSeverity}
            onChange={(event) => setCSeverity(event.target.value as ConstraintSeverity)}
            wrapperClassName="min-w-40"
          >
            <option value="aversion">{t("severity.aversion")}</option>
            <option value="intolerance">{t("severity.intolerance")}</option>
            <option value="severe_allergy">{t("severity.severe_allergy")}</option>
          </SelectField>

          <SelectField
            label={t("who")}
            value={cMember}
            onChange={(event) => setCMember(event.target.value)}
            wrapperClassName="min-w-36 flex-1"
          >
            {/* Only an aversion may float free of a member: an allergy without
                someone it belongs to is meaningless, and its household scope
                comes from its severity, not from a missing member. */}
            {!isAllergy && <option value="">{t("wholeHousehold")}</option>}
            {members.map((member) => (
              <option key={member.id} value={member.id}>
                {member.display_name}
              </option>
            ))}
          </SelectField>

          {isAllergy ? (
            <SelectField
              label={t("allergen")}
              value={cAllergen}
              onChange={(event) => setCAllergen(event.target.value as AllergenCode)}
              wrapperClassName="min-w-36 flex-1"
            >
              {ALLERGEN_CODES.map((code) => (
                <option key={code} value={code}>
                  {tAllergen(code)}
                </option>
              ))}
            </SelectField>
          ) : (
            <Field
              label={t("food")}
              value={cLabel}
              onChange={(event) => setCLabel(event.target.value)}
              wrapperClassName="min-w-36 flex-1"
            />
          )}

          <Button
            disabled={busy || (!isAllergy && !cLabel.trim()) || (isAllergy && !cMember && !members[0])}
            onClick={() =>
              run(async () => {
                const created = await apiPost<DietaryConstraint>("/household/constraints", {
                  member_id: isAllergy ? cMember || members[0]?.id : cMember || null,
                  allergen_code: isAllergy ? cAllergen : null,
                  label: isAllergy ? null : cLabel.trim(),
                  severity: cSeverity,
                });
                setConstraints((current) => [...current, created]);
                setCLabel("");
              })
            }
          >
            {tCommon("add")}
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("slotsHeading")}</h2>
          {/* The grid is declared at HOUSEHOLD level, not per member: a slot is
              a meal that happens, not a meal someone attends. */}
          <p className="text-sm text-ink-muted">{t("slotsHint")}</p>
        </div>

        <div className="overflow-x-auto">
          <table className="text-sm">
            <thead>
              <tr>
                <th className="px-2 py-1" />
                {DAYS.map((day) => (
                  <th key={day} className="px-2 py-1 font-medium text-ink-muted">
                    {t(`day.${day}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MEALS.map((meal) => (
                <tr key={meal}>
                  <th className="px-2 py-1 text-left font-medium text-ink-muted">
                    {tMeal(meal)}
                  </th>
                  {DAYS.map((day) => (
                    <td key={day} className="px-2 py-1 text-center">
                      <input
                        type="checkbox"
                        checked={enabledAt(day, meal)}
                        disabled={busy}
                        onChange={() => toggleSlot(day, meal)}
                        aria-label={`${t(`day.${day}`)} ${tMeal(meal)}`}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">{t("otherHeading")}</h2>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={snacks}
            disabled={busy}
            onChange={(event) => {
              setSnacks(event.target.checked);
              run(async () => {
                await apiPatch("/household/settings", { snacks_enabled: event.target.checked });
              });
            }}
          />
          {t("snacks")}
        </label>
        <p className="text-xs text-ink-faint">{t("snacksHint")}</p>
      </section>

      {error && <p className="text-sm text-danger">{error}</p>}
      {saved && !error && <p className="text-sm text-accent">{t("saved")}</p>}
    </div>
  );
}
