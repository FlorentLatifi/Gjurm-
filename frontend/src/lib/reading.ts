import { useCallback, useState, useSyncExternalStore } from "react";

import type { Lens } from "./ratings";

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

const KEY = "gjurme-reading";
const MAX_ENTRIES = 500;
const MAX_AGE_MS = 90 * 24 * 3600 * 1000;
const listeners = new Set<() => void>();
let cachedRaw: string | null = null;
let cached: ReadEntry[] = [];

function load(): ReadEntry[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return [];
  }
  if (raw === cachedRaw) return cached;
  cachedRaw = raw;
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    const cutoff = Date.now() - MAX_AGE_MS;
    cached = Array.isArray(parsed)
      ? parsed.filter(
          (e): e is ReadEntry =>
            typeof e === "object" && e !== null && typeof e.s === "string" &&
            /^[a-z0-9-]{2,64}$/.test(e.s) && typeof e.at === "number" && e.at >= cutoff,
        )
      : [];
  } catch {
    cached = [];
  }
  return cached;
}

function save(entries: ReadEntry[]) {
  try {
    if (entries.length) localStorage.setItem(KEY, JSON.stringify(entries.slice(-MAX_ENTRIES)));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: nothing is remembered */
  }
  listeners.forEach((l) => l());
}

export function recordRead(source: string, story: number | null = null, topic: string | null = null) {
  save([...load(), { s: source, st: story, t: topic, at: Date.now() }]);
}

export function clearReading() {
  save([]);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useReading(): ReadEntry[] {
  return useSyncExternalStore(subscribe, load, () => []);
}

// ---------------------------------------------------------------------------------------------
// Coverage lens preference (per browser)
// ---------------------------------------------------------------------------------------------
const LENS_KEY = "gjurme-lens";
const LENSES: Lens[] = ["perspective", "region", "ownership", "factuality"];

function readLens(): Lens | null {
  try {
    const v = localStorage.getItem(LENS_KEY);
    return LENSES.includes(v as Lens) ? (v as Lens) : null;
  } catch {
    return null;
  }
}

/**
 * The dimension coverage bars split by. Until the reader picks one, it is "perspective" — or
 * "region" when no outlet has a perspective rating yet (an all-"unrated" bar says nothing).
 */
export function useLens(nothingRated: boolean): [Lens, (lens: Lens) => void] {
  const [chosen, setChosen] = useState<Lens | null>(readLens);
  const choose = useCallback((lens: Lens) => {
    setChosen(lens);
    try {
      localStorage.setItem(LENS_KEY, lens);
    } catch {
      /* preference lasts for this page view only */
    }
  }, []);
  return [chosen ?? (nothingRated ? "region" : "perspective"), choose];
}
