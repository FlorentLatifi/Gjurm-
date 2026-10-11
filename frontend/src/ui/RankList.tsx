import { Link } from "react-router-dom";

import { formatInt } from "@/shared/lib/format";

export interface RankItem {
  key: string | number;
  label: string;
  href?: string;
  value: number;
  meta?: React.ReactNode;
  sublabel?: string;
}

/** Ranked horizontal bars as plain HTML: accessible by default, one hue (magnitude, not identity). */
export function RankList({ items, unit }: { items: RankItem[]; unit: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ol className="rank-list">
      {items.map((it) => (
        <li key={it.key} className="rank-row">
          <span>
            {it.href ? <Link to={it.href}>{it.label}</Link> : <span>{it.label}</span>}
            {it.sublabel && <span className="rank-meta"> · {it.sublabel}</span>}
          </span>
          <span className="rank-meta">
            {formatInt(it.value)} {unit}
            {it.meta}
          </span>
          <span className="rank-bar" style={{ width: `${(it.value / max) * 100}%` }} aria-hidden="true" />
        </li>
      ))}
    </ol>
  );
}
