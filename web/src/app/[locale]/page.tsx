import { getTranslations, setRequestLocale } from "next-intl/server";

import { apiGet } from "@/lib/api/server";
import type { Household, Member, PendingTransition } from "@/lib/api/types";

/**
 * Phase 0 skeleton. It exists to prove the seams end to end — sign-in, session
 * cookie, household derived from identity, life-stage transitions awaiting
 * confirmation — not to look like a product.
 *
 * The real UX is designed in phase 0-bis, against the FINAL API contract rather
 * than against whatever the stubs happen to return.
 */
export default async function HomePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("home");
  const stages = await getTranslations("lifeStage");

  const household = await apiGet<Household>("/household");

  if (household === null) {
    return (
      <main>
        <h1>{t("signedOutHeading")}</h1>
        <p>{t("signedOutBody")}</p>
        {/* A real browser navigation, not a Next.js route: `/api/*` is proxied
            to FastAPI, which answers with a redirect to Google. `next/link`
            would try to resolve it client-side and never leave the app. */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
        <a href="/api/auth/login">{t("signIn")}</a>
      </main>
    );
  }

  const members = (await apiGet<Member[]>("/members")) ?? [];
  const pending = (await apiGet<PendingTransition[]>("/members/pending-transitions")) ?? [];
  const nameOf = (id: string) =>
    members.find((member) => member.id === id)?.display_name ?? id;

  return (
    <main>
      <h1>{t("signedInHeading")}</h1>
      <p>{household.name}</p>

      <section>
        <h2>{t("membersHeading")}</h2>
        {members.length === 0 ? (
          <p>{t("noMembers")}</p>
        ) : (
          <ul>
            {members.map((member) => (
              <li key={member.id}>
                {member.display_name} — {stages(member.life_stage)}
              </li>
            ))}
          </ul>
        )}
      </section>

      {pending.length > 0 && (
        <section>
          {/* A stage change is proposed, never applied on its own: crossing
              baby -> young_child widens what is allowed. */}
          <h2>{t("pendingTransitionsHeading")}</h2>
          <ul>
            {pending.map((transition) => (
              <li key={transition.member_id}>
                {t("pendingTransition", {
                  name: nameOf(transition.member_id),
                  from: stages(transition.current),
                  to: stages(transition.proposed),
                })}
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
