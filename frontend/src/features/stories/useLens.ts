import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

import type { Lens } from "@/shared/model/ratings";
import { isLens, usePreferences } from "@/stores/preferences";

/**
 * The dimension coverage bars split by. A ?lens= in the URL wins, so a shared link shows what
 * its sender saw; otherwise the reader's last choice; otherwise "perspective" — or "region" while
 * no outlet has a perspective rating yet (an all-"unrated" bar says nothing).
 */
export function useLens(nothingRated: boolean): [Lens, (lens: Lens) => void] {
  const [params, setParams] = useSearchParams();
  const stored = usePreferences((s) => s.lens);
  const setStored = usePreferences((s) => s.setLens);
  const fromUrl = params.get("lens");
  const lens = isLens(fromUrl) ? fromUrl : (stored ?? (nothingRated ? "region" : "perspective"));
  const choose = useCallback(
    (next: Lens) => {
      setStored(next);
      setParams(
        (prev) => {
          const out = new URLSearchParams(prev);
          out.set("lens", next);
          return out;
        },
        { replace: true },
      );
    },
    [setParams, setStored],
  );
  return [lens, choose];
}
