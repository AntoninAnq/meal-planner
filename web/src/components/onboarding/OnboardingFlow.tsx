"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { AllergenNotice } from "@/components/constraints/AllergenNotice";
import { Button } from "@/components/ui/Button";
import { Field, SelectField } from "@/components/ui/Field";
import { ListRow } from "@/components/ui/ListRow";
import { Spinner } from "@/components/ui/Spinner";
import { useRouter } from "@/i18n/navigation";
import { apiDelete, apiPatch, apiPost } from "@/lib/api/client";
import { ApiError } from "@/lib/api/error";
import {
  ALLERGEN_CODES,
  type AllergenCode,
  type DietaryConstraint,
  type LifeStage,
  type Member,
} from "@/lib/api/types";

const LIFE_STAGES: LifeStage[] = ["baby", "young_child", "teen_adult"];

/**
 * One page, three blocks — not a three-step wizard.
 *
 * At this point nobody has seen a single menu, so they have no reason to trust
 * the product. A single page shows the whole cost at a glance ("thirty
 * seconds, and that is all I am asked"); a wizard hides its own length, and
 * every step you clear might reveal another.
 *
 * Writes are immediate rather than collected and submitted at the end: an
 * allergy belongs to a member, so the member has to exist first — and a form
 * that can lose ten minutes of typing to a reload is worse than one extra
 * request per person.
 */
export function OnboardingFlow({
  initialMembers,
  initialConstraints,
}: {
  initialMembers: Member[];
  initialConstraints: DietaryConstraint[];
}) {
  const t = useTranslations("onboarding");
  const tCommon = useTranslations("common");
  const tStage = useTranslations("lifeStage");
  const tAllergen = useTranslations("allergen");
  const router = useRouter();

  const [members, setMembers] = useState(initialMembers);
  const [allergies, setAllergies] = useState(
    initialConstraints.filter((c) => c.allergen_code !== null),
  );

  const [name, setName] = useState("");
  const [stage, setStage] = useState<LifeStage>("teen_adult");
  const [allergyMember, setAllergyMember] = useState("");
  const [allergen, setAllergen] = useState<AllergenCode>("gluten");
  const [dislikes, setDislikes] = useState("");

  // An already-declared allergy forces the question open: hiding it behind a
  // "nobody" radio would leave a constraint the user can no longer see.
  const [saysYes, setSaysYes] = useState(false);
  const showAllergyForm = saysYes || allergies.length > 0;

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : tCommon("genericError"));
    } finally {
      setBusy(false);
    }
  }

  const addMember = () =>
    run(async () => {
      const created = await apiPost<Member>("/members", {
        display_name: name.trim(),
        life_stage: stage,
      });
      setMembers((current) => [...current, created]);
      setName("");
    });

  const removeMember = (member: Member) =>
    run(async () => {
      await apiDelete(`/members/${member.id}`);
      setMembers((current) => current.filter((m) => m.id !== member.id));
      // The allergies that belonged to them went with the member server-side.
      setAllergies((current) => current.filter((c) => c.member_id !== member.id));
    });

  const addAllergy = () =>
    run(async () => {
      const created = await apiPost<DietaryConstraint>("/household/constraints", {
        member_id: selectedMember,
        allergen_code: allergen,
        severity: "severe_allergy",
      });
      setAllergies((current) => [...current, created]);
    });

  const removeAllergy = (constraint: DietaryConstraint) =>
    run(async () => {
      await apiDelete(`/household/constraints/${constraint.id}`);
      setAllergies((current) => current.filter((c) => c.id !== constraint.id));
    });

  const finish = () =>
    run(async () => {
      // One constraint per disliked food rather than one blob: each can then be
      // narrowed down to a person, which is what makes it argue for a second
      // dish instead of removing the ingredient for everyone.
      for (const label of dislikes.split(",").map((part) => part.trim())) {
        if (!label) continue;
        await apiPost("/household/constraints", { label, severity: "aversion" });
      }
      await apiPatch("/household/settings", { onboarding_complete: true });
      router.push("/");
      router.refresh();
    });

  const nameOf = (id: string | null) =>
    members.find((member) => member.id === id)?.display_name ?? "?";

  // Removing the person an allergy was about to be attached to would otherwise
  // leave a stale id selected: the select renders blank and the POST 404s.
  const selectedMember =
    members.find((member) => member.id === allergyMember)?.id ?? members[0]?.id;

  return (
    <div className="flex flex-col gap-10">
      {/* --- Block 1: members ------------------------------------------- */}
      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("membersHeading")}</h2>
          <p className="text-sm text-ink-muted">{t("membersHint")}</p>
        </div>

        {members.length === 0 ? (
          <p className="text-sm text-ink-faint">{t("noMembers")}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {members.map((member) => (
              <ListRow
                key={member.id}
                action={
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => removeMember(member)}
                    aria-label={t("removeMember", { name: member.display_name })}
                  >
                    {tCommon("remove")}
                  </Button>
                }
              >
                <strong className="font-medium">{member.display_name}</strong>
                <span className="text-ink-muted"> — {tStage(member.life_stage)}</span>
              </ListRow>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <Field
            label={t("nameLabel")}
            placeholder={t("namePlaceholder")}
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && name.trim() && !busy) addMember();
            }}
            wrapperClassName="min-w-40 flex-1"
          />
          <SelectField
            label={t("stageLabel")}
            value={stage}
            onChange={(event) => setStage(event.target.value as LifeStage)}
            wrapperClassName="min-w-40"
          >
            {LIFE_STAGES.map((value) => (
              <option key={value} value={value}>
                {tStage(value)}
              </option>
            ))}
          </SelectField>
          <Button variant="secondary" disabled={busy || !name.trim()} onClick={addMember}>
            {tCommon("add")}
          </Button>
        </div>
        <p className="text-xs text-ink-faint">{tStage("hint")}</p>
      </section>

      {/* --- Block 2: the allergy question ------------------------------- */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">{t("allergiesHeading")}</h2>

        {members.length === 0 ? (
          <p className="text-sm text-ink-faint">{t("allergiesLocked")}</p>
        ) : (
          <>
            {/* "Nobody" is pre-selected, not a box to tick: the question is
                asked — it is on screen, it cannot be missed — and costs the
                majority case no gesture at all. */}
            <fieldset className="flex flex-col gap-2">
              <legend className="sr-only">{t("allergiesHeading")}</legend>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="has-allergy"
                  checked={!showAllergyForm}
                  disabled={allergies.length > 0}
                  onChange={() => setSaysYes(false)}
                />
                {t("allergyNo")}
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="has-allergy"
                  checked={showAllergyForm}
                  onChange={() => setSaysYes(true)}
                />
                {t("allergyYes")}
              </label>
            </fieldset>

            {showAllergyForm && (
              <div className="flex flex-col gap-3">
                <AllergenNotice />

                {allergies.length > 0 && (
                  <ul className="flex flex-col gap-2">
                    {allergies.map((constraint) => (
                      <ListRow
                        key={constraint.id}
                        action={
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy}
                            onClick={() => removeAllergy(constraint)}
                          >
                            {tCommon("remove")}
                          </Button>
                        }
                      >
                        {t("allergyRow", {
                          name: nameOf(constraint.member_id),
                          allergen: tAllergen(constraint.allergen_code ?? "gluten"),
                        })}
                      </ListRow>
                    ))}
                  </ul>
                )}

                <div className="flex flex-wrap items-end gap-3">
                  <SelectField
                    label={t("allergyMember")}
                    value={selectedMember}
                    onChange={(event) => setAllergyMember(event.target.value)}
                    wrapperClassName="min-w-40 flex-1"
                  >
                    {members.map((member) => (
                      <option key={member.id} value={member.id}>
                        {member.display_name}
                      </option>
                    ))}
                  </SelectField>
                  <SelectField
                    label={t("allergyCode")}
                    value={allergen}
                    onChange={(event) => setAllergen(event.target.value as AllergenCode)}
                    wrapperClassName="min-w-40 flex-1"
                  >
                    {ALLERGEN_CODES.map((code) => (
                      <option key={code} value={code}>
                        {tAllergen(code)}
                      </option>
                    ))}
                  </SelectField>
                  <Button variant="secondary" disabled={busy} onClick={addAllergy}>
                    {tCommon("add")}
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </section>

      {/* --- Block 3: household aversions -------------------------------- */}
      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("dislikesHeading")}</h2>
          <p className="text-sm text-ink-muted">{t("dislikesHint")}</p>
        </div>
        <Field
          label={t("dislikesLabel")}
          placeholder={t("dislikesPlaceholder")}
          value={dislikes}
          onChange={(event) => setDislikes(event.target.value)}
        />
      </section>

      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="flex items-center gap-3">
        <Button variant="primary" disabled={busy || members.length === 0} onClick={finish}>
          {busy && <Spinner label={tCommon("saving")} />}
          {t("finish")}
        </Button>
        {members.length === 0 && (
          <span className="text-sm text-ink-muted">{t("needsMember")}</span>
        )}
      </div>
    </div>
  );
}
