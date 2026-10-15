/**
 * localStorage that never throws. Private windows, blocked site data and full quotas make the
 * Storage API throw; GJURMË must keep working then, simply without remembering anything.
 */
export const safeStorage = {
  getItem(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key: string, value: string): void {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* storage unavailable: the value lasts for this page view only */
    }
  },
  removeItem(key: string): void {
    try {
      localStorage.removeItem(key);
    } catch {
      /* nothing to remove */
    }
  },
};

/**
 * Re-read a persisted store when another tab of this site changed it, so two open tabs agree.
 * Returns the unsubscribe function.
 */
export function syncAcrossTabs(key: string, rehydrate: () => unknown): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === key || e.key === null) void rehydrate();
  };
  window.addEventListener("storage", onStorage);
  return () => window.removeEventListener("storage", onStorage);
}
