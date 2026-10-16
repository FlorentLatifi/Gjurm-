import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

import type { Lens } from "@/shared/model/ratings";
import { isLens, usePreferences } from "@/stores/preferences";

/**
 * The dimension coverage bars split by. A ?lens= in the URL wins, so a shared link shows what
 * its sender saw; otherwise the reader's last choice; otherwise "perspective". Only a lens in
 * ``available`` is used (``availableLenses``: no all-"unrated" perspective bars while no outlet
 * is rated, whatever the link or the stored choice says), falling back to "region".
 * ``available`` is null while the page's data loads.
 */
export function useLens(available: Lens[] | null): [Lens, (lens: Lens) => void] {
  const [params, setParams] = useSearchParams();
  const stored = usePreferences((s) => s.lens);
  const setStored = usePreferences((s) => s.setLens);
  const fromUrl = params.get("lens");
  const usable = (l: string | null | undefined): l is Lens => isLens(l) && (available === null || available.includes(l));
  const lens = usable(fromUrl) ? fromUrl : usable(stored) ? stored : usable("perspective") ? "perspective" : "region";
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
