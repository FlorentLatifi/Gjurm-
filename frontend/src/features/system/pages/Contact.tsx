import type { Lang } from "@/shared/i18n";

import { CONTACT_IS_EMAIL, CONTACT_URL } from "./about";

/**
 * The address for corrections, removal and privacy requests, in the page's language. It is the
 * private mailbox when VITE_CONTACT_URL is a mailto:, otherwise the project's public issue page
 * (see about.ts), and the text says which, so nobody posts something private in public.
 */
export function ContactLink({ lang }: { lang: Lang }) {
  if (CONTACT_IS_EMAIL) return <a href={CONTACT_URL}>{CONTACT_URL.slice("mailto:".length)}</a>;
  return (
    <a href={CONTACT_URL} rel="noopener noreferrer">
      {lang === "sq" ? "depoja e projektit (kërkesat janë publike)" : "the project repository (issues are public)"}
    </a>
  );
}
