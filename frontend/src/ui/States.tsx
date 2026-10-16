import { Link } from "react-router-dom";

import { ApiError } from "@/shared/api/client";
import { getLang, t, tn } from "@/shared/i18n";

export function Skeleton({ height = 16, width = "100%" }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden="true" />;
}

export function LoadingBlock({ height = 220, label }: { height?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite">
      <span className="visually-hidden">{label ?? t("Loading")}…</span>
      <Skeleton height={height} />
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  let message = t("Something went wrong while loading this data.");
  if (error instanceof ApiError) {
    if (error.code === "rate_limited") {
      message = error.retryAfter
        ? tn(error.retryAfter, "Too many requests — please wait {n} second.", "Too many requests — please wait {n} seconds.")
        : t("Too many requests — please wait a few seconds.");
    } else if (error.code === "timeout") {
      message = t("The server took too long to respond.");
    } else if (error.code === "network") {
      message = t("Could not reach the GJURMË API. Check your connection.");
    } else if (error.status >= 500) {
      message = t("The server could not answer just now. Please try again in a moment.");
    } else if (error.status === 404) {
      message = t("Not found.");
    } else if (getLang() === "en") {
      message = error.message; // the API explains a rejected request in English
    }
  }
  return (
    <div className="state state--error" role="alert">
      <p>{message}</p>
      {onRetry && (
        <button type="button" className="btn btn--sm" onClick={onRetry}>
          {t("Try again")}
        </button>
      )}
    </div>
  );
}

/** A page-level "not found": what is missing, and the ways on from here. */
export function NotFoundState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="state state--page">
      <h1>{title}</h1>
      <p>{children ?? t("The page you are looking for does not exist.")}</p>
      <p className="state__actions">
        <Link className="btn" to="/">{t("Go to the top stories")}</Link>
        <Link to="/articles">{t("Search the articles")}</Link>
      </p>
    </div>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="state">
      <p>{children}</p>
    </div>
  );
}
