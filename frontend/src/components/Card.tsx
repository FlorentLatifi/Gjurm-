import { useId, useState, type ReactNode } from "react";

import { EmptyState, ErrorState, LoadingBlock } from "./States";

interface QueryLike {
  isPending: boolean;
  isError: boolean;
  isPlaceholderData?: boolean;
  isFetching?: boolean;
  error: unknown;
  refetch: () => unknown;
}

interface CardProps {
  title: string;
  /** The analytical question this card answers — shown under the title. */
  question?: string;
  /** Plain-language method, rendered as a footnote. */
  method?: string;
  query?: QueryLike;
  empty?: boolean;
  emptyText?: string;
  /** Table view of the same data (accessibility equivalent of the chart). */
  table?: () => ReactNode;
  actions?: ReactNode;
  loadingHeight?: number;
  children: () => ReactNode;
  className?: string;
}

/**
 * Every chart lives in a Card: consistent title + question, loading skeleton on first load,
 * dimmed previous render on refetch (no layout jump), explicit error and empty states, and a
 * "Table" toggle so no value is only reachable through a chart or tooltip.
 */
export function Card({
  title,
  question,
  method,
  query,
  empty,
  emptyText = "No data for this period yet.",
  table,
  actions,
  loadingHeight,
  children,
  className = "",
}: CardProps) {
  const [showTable, setShowTable] = useState(false);
  const headingId = useId();
  const refetching = Boolean(query?.isPlaceholderData && query?.isFetching);

  let body: ReactNode;
  if (query?.isPending) body = <LoadingBlock height={loadingHeight} label={`Loading ${title}`} />;
  else if (query?.isError) body = <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  else if (empty) body = <EmptyState>{emptyText}</EmptyState>;
  else body = showTable && table ? <div className="table-wrap">{table()}</div> : children();

  return (
    <section
      className={`card ${refetching ? "card--refetching" : ""} ${className}`}
      aria-labelledby={headingId}
      aria-busy={query?.isPending || refetching || undefined}
    >
      <div className="card__head">
        <div>
          <h2 id={headingId}>{title}</h2>
          {question && <p className="card__question">{question}</p>}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {actions}
          {table && !query?.isPending && !query?.isError && !empty && (
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              aria-pressed={showTable}
              onClick={() => setShowTable((v) => !v)}
            >
              {showTable ? "Chart" : "Table"}
            </button>
          )}
        </div>
      </div>
      {body}
      {method && <p className="card__foot">{method}</p>}
    </section>
  );
}
