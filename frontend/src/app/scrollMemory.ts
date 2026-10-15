import { useEffect, useLayoutEffect } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

/**
 * Scroll positions per path, for this tab. Back/forward returns to where the reader was; any
 * other navigation to a new path starts at the top; filter and page changes (same path) keep
 * the position. Restoring retries for up to a second, because the page may still be filling in
 * (its code or data arriving) when it first renders — a single scrollTo would stop short.
 */
const positions = new Map<string, number>();
let currentPath = "";

function remember() {
  if (currentPath) positions.set(currentPath, window.scrollY);
}

export function useScrollMemory() {
  const { pathname } = useLocation();
  const navigation = useNavigationType();

  useEffect(() => {
    if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";
    window.addEventListener("scroll", remember, { passive: true });
    return () => window.removeEventListener("scroll", remember);
  }, []);

  useLayoutEffect(() => {
    // from here on, scroll events belong to the new path (including the one scrollTo causes)
    currentPath = pathname;
    if (navigation !== "POP") {
      window.scrollTo(0, 0);
      return;
    }
    const target = positions.get(pathname);
    if (target === undefined) return;
    let frame = 0;
    let tries = 0;
    const attempt = () => {
      window.scrollTo(0, target);
      if (Math.abs(window.scrollY - target) > 2 && tries++ < 60) frame = requestAnimationFrame(attempt);
    };
    // the reader takes over: stop restoring
    const stop = () => cancelAnimationFrame(frame);
    window.addEventListener("wheel", stop, { once: true, passive: true });
    window.addEventListener("touchstart", stop, { once: true, passive: true });
    attempt();
    return () => {
      stop();
      window.removeEventListener("wheel", stop);
      window.removeEventListener("touchstart", stop);
    };
  }, [pathname, navigation]);
}
