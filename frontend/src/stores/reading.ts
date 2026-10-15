import { create } from "zustand";
import { persist, type PersistStorage } from "zustand/middleware";

import { safeStorage } from "./storage";

/**
 * "My news bias": which outlets this reader opened, kept ONLY in this browser (localStorage).
 * Nothing is sent to the server. Entries are capped in number and age, and the reader can clear
 * them at any time. When storage is unavailable (private mode, blocked), everything still works
 * and simply records nothing.
 */
export interface ReadEntry {
  /** source slug */
  s: string;
  /** story id, if the article belongs to one */
  st: number | null;
  /** topic slug */
  t: string | null;
  /** epoch ms */
  at: number;
}

export const READING_KEY = "gjurme-reading";
const MAX_ENTRIES = 500;
const MAX_AGE_MS = 90 * 24 * 3600 * 1000;

interface ReadingState {
  entries: ReadEntry[];
  record: (source: string, story?: number | null, topic?: string | null) => void;
  clear: () => void;
}

function valid(e: unknown, cutoff: number): e is ReadEntry {
  if (typeof e !== "object" || e === null) return false;
  const r = e as Partial<ReadEntry>;
  return typeof r.s === "string" && /^[a-z0-9-]{2,64}$/.test(r.s) && typeof r.at === "number" && r.at >= cutoff;
}

/**
 * Stored as a plain array (the format used since the feature shipped), not zustand's
 * {state, version} envelope, so existing reading histories keep working.
 */
const storage: PersistStorage<Pick<ReadingState, "entries">> = {
  getItem(name) {
    const raw = safeStorage.getItem(name);
    if (!raw) return null;
    try {
      const parsed: unknown = JSON.parse(raw);
      const cutoff = Date.now() - MAX_AGE_MS;
      const entries = Array.isArray(parsed) ? parsed.filter((e) => valid(e, cutoff)) : [];
      return { state: { entries }, version: 0 };
    } catch {
      return { state: { entries: [] }, version: 0 };
    }
  },
  setItem(name, value) {
    const entries = value.state.entries.slice(-MAX_ENTRIES);
    if (entries.length) safeStorage.setItem(name, JSON.stringify(entries));
    else safeStorage.removeItem(name);
  },
  removeItem(name) {
    safeStorage.removeItem(name);
  },
};

export const useReadingStore = create<ReadingState>()(
  persist(
    (set) => ({
      entries: [],
      record: (source, story = null, topic = null) =>
        set((s) => ({ entries: [...s.entries, { s: source, st: story, t: topic, at: Date.now() }].slice(-MAX_ENTRIES) })),
      clear: () => set({ entries: [] }),
    }),
    { name: READING_KEY, storage, partialize: (s) => ({ entries: s.entries }) },
  ),
);

export function recordRead(source: string, story: number | null = null, topic: string | null = null) {
  useReadingStore.getState().record(source, story, topic);
}

export function clearReading() {
  useReadingStore.getState().clear();
}

/** Every entry (the My news bias page). */
export function useReading(): ReadEntry[] {
  return useReadingStore((s) => s.entries);
}

/** Only the count, so a component showing it does not re-render for anything else. */
export function useReadingCount(): number {
  return useReadingStore((s) => s.entries.length);
}
