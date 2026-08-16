import { useTranslations } from "next-intl";

import { cx } from "@/lib/cx";

/**
 * The one place this interface raises its voice.
 *
 * V0 has no catalogue, so there is no ingredient list, no verified tag and no
 * allergen filter — the model is merely *told* about the allergy. The
 * architecture accepted that on the condition the app stayed with its author;
 * the moment anyone else tries it, the missing guarantee has to be stated
 * where allergies are entered and on the generated plan, not in a document
 * nobody reads.
 *
 * This component is deleted in V1, when the filter becomes real.
 */
export function AllergenNotice({ className }: { className?: string }) {
  const t = useTranslations("allergenNotice");

  return (
    <div
      role="note"
      className={cx(
        "rounded-card border border-danger/30 bg-danger-soft px-4 py-3",
        className,
      )}
    >
      <p className="text-sm font-semibold text-danger">{t("heading")}</p>
      <p className="mt-1 text-sm text-ink">{t("body")}</p>
    </div>
  );
}
