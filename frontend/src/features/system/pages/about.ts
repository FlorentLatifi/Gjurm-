import type { PublicStatus } from "@/shared/api/types";

// Where correction, removal and privacy requests go: the operator's mailbox, so nobody has to post
// them publicly. VITE_CONTACT_URL at build time (a mailto: or https: address) overrides it.
export const CONTACT_URL = /^(mailto:|https:\/\/)/.test(import.meta.env.VITE_CONTACT_URL ?? "")
  ? (import.meta.env.VITE_CONTACT_URL as string)
  : "mailto:florentlatifi123@gmail.com";
export const CONTACT_IS_EMAIL = CONTACT_URL.startsWith("mailto:");

/** What both language versions of the methodology page show from live data. */
export interface AboutProps {
  topics: number;
  status: PublicStatus | undefined;
}
