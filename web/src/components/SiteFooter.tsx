import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";

/**
 * Where a stranger says what they thought.
 *
 * Rendered on EVERY screen, including the sign-in one — deliberately. Someone
 * who reads the pitch and leaves without signing in is the feedback hardest to
 * get and the most worth having, and a link that only exists behind the login
 * never reaches them.
 *
 * The destination is configuration, not code (I8). A hosted form and a
 * `mailto:` are both valid values, and the choice between them is a deployment
 * decision that should never need a commit — the address may also be personal,
 * which is not a thing to put in a public repository.
 *
 * Unset means no link at all rather than a dead one. A footer inviting
 * feedback into a 404 is worse than no footer.
 */
export async function SiteFooter() {
  const destination = process.env.FEEDBACK_URL;
  const t = await getTranslations("account");
  const tTerms = await getTranslations("terms");

  return (
    <footer className="mx-auto flex max-w-5xl flex-wrap gap-4 px-5 pb-8 text-sm text-ink-faint">
      {destination && (
        <a
          href={destination}
          // `noreferrer` matters for the hosted-form case: without it the form
          // provider is told which page the household came from, and this one is
          // about who eats what.
          target="_blank"
          rel="noreferrer noopener"
          className="underline underline-offset-4 transition-colors hover:text-ink-muted"
        >
          {t("feedback")}
        </a>
      )}
      {/* Always, unlike the feedback link: a household can write a text other
          households will read, and the rules for that have to be reachable
          from every screen rather than from a deployment variable. */}
      <Link
        href="/terms"
        className="underline underline-offset-4 transition-colors hover:text-ink-muted"
      >
        {tTerms("footer")}
      </Link>
    </footer>
  );
}
