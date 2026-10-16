import type { PublicStatus } from "@/shared/api/types";

// Where correction and removal requests go. Set VITE_CONTACT_URL at build time (e.g. a mailto:
// address) so people do not have to post removal requests publicly; GitHub issues are public.
export const CONTACT_URL = /^(mailto:|https:\/\/)/.test(import.meta.env.VITE_CONTACT_URL ?? "")
  ? (import.meta.env.VITE_CONTACT_URL as string)
  : "https://github.com/FlorentLatifi/Gjurm-/issues";
export const CONTACT_IS_EMAIL = CONTACT_URL.startsWith("mailto:");

/** What both language versions of the methodology page show from live data. */
export interface AboutProps {
  topics: number;
  status: PublicStatus | undefined;
}
