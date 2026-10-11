import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { Lens } from "@/shared/model/ratings";

import { safeStorage } from "./storage";

export type Theme = "light" | "dark" | "system";

const LENSES: readonly Lens[] = ["perspective", "region", "ownership", "factuality"];
export const PREFERENCES_KEY = "gjurme-prefs";

export function isLens(value: unknown): value is Lens {
  return typeof value === "string" && (LENSES as readonly string[]).includes(value);
}

function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark" || value === "system";
}

/** Settings saved before this store existed lived under their own keys; read them once. */
function legacyTheme(): Theme {
  const t = safeStorage.getItem("gjurme-theme");
  return t === "light" || t === "dark" ? t : "system";
}

function legacyLens(): Lens | null {
  const l = safeStorage.getItem("gjurme-lens");
  return isLens(l) ? l : null;
}

export interface Preferences {
  theme: Theme;
  /** The coverage lens this reader last chose; the URL (?lens=) overrides it for one view. */
  lens: Lens | null;
  setTheme: (theme: Theme) => void;
  setLens: (lens: Lens) => void;
}

/**
 * Per-browser preferences (ADR-022: nothing leaves the browser). public/theme.js reads the same
 * key before first paint, so the stored theme applies without a flash.
 */
export const usePreferences = create<Preferences>()(
  persist(
    (set) => ({
      theme: legacyTheme(),
      lens: legacyLens(),
      setTheme: (theme) => set({ theme }),
      setLens: (lens) => set({ lens }),
    }),
    {
      name: PREFERENCES_KEY,
      version: 1,
      storage: createJSONStorage(() => safeStorage),
      partialize: (s) => ({ theme: s.theme, lens: s.lens }),
      // never trust stored values: a corrupted or hand-edited entry falls back to the defaults
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<Preferences>;
        return {
          ...current,
          theme: isTheme(p.theme) ? p.theme : current.theme,
          lens: isLens(p.lens) ? p.lens : current.lens,
        };
      },
    },
  ),
);
