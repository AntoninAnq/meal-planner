import { getTranslations, setRequestLocale } from "next-intl/server";

import { Link } from "@/i18n/navigation";

/**
 * The terms, and they exist for one reason: a household can now write a text
 * that other households read.
 *
 * Kept to what is actually true of this product rather than padded into the
 * usual wall. Everything here is a promise the code already keeps — what is
 * stored, what leaves a household, what happens on a complaint — because terms
 * that describe a different product are worse than none.
 *
 * The contact is `FEEDBACK_URL`, the address the footer already uses (I8): a
 * takedown request has to reach a person, and a page promising a channel that
 * is not configured would be a lie. Without it, the page says to use the
 * feedback link instead of naming an address that does not exist.
 */
export default async function TermsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("terms");
  const contact = process.env.FEEDBACK_URL;

  const sections = ["data", "recipes", "sharing", "takedown", "liability"] as const;

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-7 px-5 py-10">
      <header className="flex flex-col gap-2">
        <Link href="/" className="text-sm text-ink-muted hover:text-ink">
          ← {t("back")}
        </Link>
        <h1 className="text-2xl font-semibold text-ink">{t("heading")}</h1>
        <p className="max-w-[70ch] text-sm leading-[1.55] text-ink-body">{t("intro")}</p>
      </header>

      {sections.map((section) => (
        <section key={section} className="flex flex-col gap-2">
          <h2 className="text-[17px] font-semibold text-ink">{t(`${section}.heading`)}</h2>
          <p className="max-w-[70ch] text-sm leading-[1.6] text-ink-body">
            {t(`${section}.body`)}
          </p>
        </section>
      ))}

      <section className="flex flex-col gap-2">
        <h2 className="text-[17px] font-semibold text-ink">{t("contact.heading")}</h2>
        <p className="max-w-[70ch] text-sm leading-[1.6] text-ink-body">
          {contact ? (
            <a
              href={contact}
              target="_blank"
              rel="noreferrer noopener"
              className="text-accent underline underline-offset-4 hover:text-accent-hover"
            >
              {t("contact.link")}
            </a>
          ) : (
            t("contact.unset")
          )}
        </p>
      </section>
    </main>
  );
}
