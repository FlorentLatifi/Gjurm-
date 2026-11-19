/**
 * Who runs GJURMË: the facts the "Who we are" and "Privacy" pages state about the operator.
 * One place, so a change is one edit. The contact address is not here: it is CONTACT_URL
 * (about.ts), set at build time through VITE_CONTACT_URL, and shared with the methodology page.
 */
export const OPERATOR = {
  /** The person who runs the project (a personal project, not a company). */
  name: "Florent Latifi",
  /** City and country the operator is based in. */
  place: "Prishtinë, Kosovë",
  /** How long an outlet or reader waits for an answer to a correction request. */
  replyWithin: { sq: "3 ditë", en: "3 days" },
} as const;
