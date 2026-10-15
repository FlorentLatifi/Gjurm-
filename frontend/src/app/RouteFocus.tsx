import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

/**
 * On client-side navigation, move focus to the main landmark so screen readers announce the new
 * page (scrolling is ScrollRestoration's job). Not on the initial load: keyboard users must start
 * at the skip link / nav. A separate component, so only it (not the whole shell) subscribes to
 * the location.
 */
export function RouteFocus() {
  const { pathname } = useLocation();
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    document.getElementById("main")?.focus({ preventScroll: true });
  }, [pathname]);
  return null;
}
