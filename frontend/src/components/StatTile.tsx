import { formatChange } from "../lib/format";
import { Skeleton } from "./States";

interface StatTileProps {
  label: string;
  value: string;
  sub?: string;
  /** Relative change (0.12 = +12%) vs the named period. */
  delta?: number | null;
  deltaLabel?: string;
  /** Whether an increase is good (green) or merely neutral information. */
  upIsGood?: boolean | null;
  textValue?: boolean;
  loading?: boolean;
}

export function StatTile({
  label,
  value,
  sub,
  delta,
  deltaLabel,
  upIsGood = null,
  textValue,
  loading,
}: StatTileProps) {
  let deltaClass = "delta--flat";
  if (delta !== undefined && delta !== null && upIsGood !== null && Math.abs(delta) >= 0.005) {
    const good = delta > 0 === upIsGood;
    deltaClass = good ? "delta--up" : "delta--down";
  }
  return (
    <div className="card stat">
      <span className="stat__label">{label}</span>
      {loading ? (
        <Skeleton height={34} width="60%" />
      ) : (
        <span className={`stat__value ${textValue ? "stat__value--text" : ""}`}>{value}</span>
      )}
      {!loading && delta !== undefined && delta !== null && (
        <span className={`delta ${deltaClass}`}>
          <span aria-hidden="true">{delta > 0 ? "▲ " : delta < 0 ? "▼ " : ""}</span>
          {formatChange(delta)} {deltaLabel}
        </span>
      )}
      {!loading && sub && <span className="stat__sub">{sub}</span>}
    </div>
  );
}
