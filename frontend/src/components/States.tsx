import { ApiError } from "../api/client";

export function Skeleton({ height = 16, width = "100%" }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden="true" />;
}

export function LoadingBlock({ height = 220, label = "Loading" }: { height?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite">
      <span className="visually-hidden">{label}…</span>
      <Skeleton height={height} />
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  let message = "Something went wrong while loading this data.";
  if (error instanceof ApiError) {
    message =
      error.code === "rate_limited"
        ? `Too many requests — please wait ${
            error.retryAfter === 1 ? "1 second" : `${error.retryAfter ?? "a few"} seconds`
          }.`
        : error.message;
  }
  return (
    <div className="state state--error" role="alert">
      <p>{message}</p>
      {onRetry && (
        <button type="button" className="btn btn--sm" onClick={onRetry}>
          Try again
        </button>
      )}
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
