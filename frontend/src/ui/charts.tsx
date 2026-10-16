/**
 * Chart primitives. Rules (see docs/DECISIONS.md ADR-011, dataviz method):
 * thin marks (bars ≤ 24px, 4px rounded data-end), 2px lines, hairline recessive grid, one y-axis
 * per chart (never dual-axis), legend whenever ≥ 2 series, text in ink tokens (never series colour),
 * tooltips that never gate (every chart has a table twin in its Card), colours from CSS tokens so
 * light/dark are validated step sets, animation off for reduced-motion users.
 */
import { useSyncExternalStore } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  Rectangle,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { SentimentPoint, VolumePoint } from "@/shared/api/types";
import { t } from "@/shared/i18n";
import { formatChange, formatDay, formatDecimal, formatInt, formatPercent, formatScore } from "@/shared/lib/format";
import "./charts.css";

const AXIS_TICK = { fill: "var(--ink-muted)", fontSize: 11 };
const GRID = { stroke: "var(--grid)", vertical: false } as const;

function subscribeMotion(cb: () => void) {
  const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  mq?.addEventListener?.("change", cb);
  return () => mq?.removeEventListener?.("change", cb);
}
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeMotion,
    () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false,
    () => true,
  );
}

// ---------------------------------------------------------------------------------------------
// Legend & tooltip
// ---------------------------------------------------------------------------------------------
export interface LegendItem {
  label: string;
  color: string;
  kind?: "swatch" | "line";
}

export function Legend({ items }: { items: LegendItem[] }) {
  return (
    <ul className="legend" aria-label={t("Legend")}>
      {items.map((it) => (
        <li key={it.label} className="legend__item">
          <span
            className={it.kind === "line" ? "legend__line" : "legend__swatch"}
            style={{ background: it.color }}
            aria-hidden="true"
          />
          {it.label}
        </li>
      ))}
    </ul>
  );
}

interface TipRow {
  label: string;
  value: string;
  color: string;
}

function TipBox({ title, rows }: { title: string; rows: TipRow[] }) {
  return (
    <div className="tooltip">
      <div className="tooltip__title">{title}</div>
      {rows.map((r) => (
        <div className="tooltip__row" key={r.label}>
          <span className="legend__line" style={{ background: r.color }} aria-hidden="true" />
          <span>{r.label}</span>
          <strong>{r.value}</strong>
        </div>
      ))}
    </div>
  );
}

/** Structural subset of recharts' tooltip props — all we need, and assignable to its generics. */
interface TipProps {
  active?: boolean;
  payload?: readonly { payload?: unknown }[];
}

function makeTooltip<T>(title: (d: T) => string, rows: (d: T) => TipRow[]) {
  return function ChartTip({ active, payload }: TipProps) {
    const datum = payload?.[0]?.payload as T | undefined;
    if (!active || !datum) return null;
    return <TipBox title={title(datum)} rows={rows(datum)} />;
  };
}

// ---------------------------------------------------------------------------------------------
// Volume: daily columns (context) + 7-day moving average (accent) on ONE axis
// ---------------------------------------------------------------------------------------------
const VolumeTip = makeTooltip<VolumePoint>(
  (d) => formatDay(d.day, true),
  (d) => [
    { label: t("Articles"), value: formatInt(d.articles), color: "var(--bar-muted)" },
    { label: t("7-day average"), value: d.ma7 === null ? "—" : formatDecimal(d.ma7), color: "var(--series-1)" },
    { label: t("Distinct stories"), value: formatInt(d.stories), color: "transparent" },
  ],
);

export function VolumeChart({ data, height = 260 }: { data: VolumePoint[]; height?: number }) {
  const still = useReducedMotion();
  const total = data.reduce((s, d) => s + d.articles, 0);
  const last = data.at(-1);
  return (
    <figure className="chart-figure">
      <Legend
        items={[
          { label: t("Articles per day"), color: "var(--bar-muted)" },
          { label: t("7-day average"), color: "var(--series-1)", kind: "line" },
        ]}
      />
      <div
        role="img"
        aria-label={
          last?.ma7 != null
            ? t("Articles per day over {days} days: {total} in total, 7-day average now {avg} per day.", {
                days: data.length, total: formatInt(total), avg: formatDecimal(last.ma7),
              })
            : t("Articles per day over {days} days: {total} in total.", { days: data.length, total: formatInt(total) })
        }
      >
        <ResponsiveContainer width="100%" height={height}>
          <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="day" tickFormatter={(d: string) => formatDay(d)} tick={AXIS_TICK}
              tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={24} />
            <YAxis allowDecimals={false} tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} />
            <Tooltip content={VolumeTip} cursor={{ fill: "var(--hover-wash)" }} />
            <Bar dataKey="articles" fill="var(--bar-muted)" radius={[4, 4, 0, 0]} maxBarSize={24}
              isAnimationActive={!still} />
            <Line dataKey="ma7" stroke="var(--series-1)" strokeWidth={2} dot={false}
              activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} isAnimationActive={!still} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

// ---------------------------------------------------------------------------------------------
// Sentiment mix: 100% stacked columns on the diverging palette (red / gray / blue)
// ---------------------------------------------------------------------------------------------
const SentimentTip = makeTooltip<SentimentPoint>(
  (d) => formatDay(d.day, true),
  (d) => {
    const n = d.negative + d.neutral + d.positive;
    return [
      { label: t("Positive"), value: `${formatInt(d.positive)} (${formatPercent(n ? d.positive / n : null)})`,
        color: "var(--sent-positive)" },
      { label: t("Neutral"), value: `${formatInt(d.neutral)} (${formatPercent(n ? d.neutral / n : null)})`,
        color: "var(--sent-neutral)" },
      { label: t("Negative"), value: `${formatInt(d.negative)} (${formatPercent(n ? d.negative / n : null)})`,
        color: "var(--sent-negative)" },
    ];
  },
);

export function SentimentMixChart({ data, height = 240 }: { data: SentimentPoint[]; height?: number }) {
  const still = useReducedMotion();
  const sums = data.reduce(
    (a, d) => ({ n: a.n + d.negative, u: a.u + d.neutral, p: a.p + d.positive }),
    { n: 0, u: 0, p: 0 },
  );
  const total = sums.n + sums.u + sums.p;
  return (
    <figure className="chart-figure">
      <Legend
        items={[
          { label: t("Positive"), color: "var(--sent-positive)" },
          { label: t("Neutral"), color: "var(--sent-neutral)" },
          { label: t("Negative"), color: "var(--sent-negative)" },
        ]}
      />
      <div
        role="img"
        aria-label={t("Share of articles by tone per day. Over the period: {p} positive, {u} neutral, {n} negative.", {
          p: formatPercent(total ? sums.p / total : null),
          u: formatPercent(total ? sums.u / total : null),
          n: formatPercent(total ? sums.n / total : null),
        })}
      >
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={data} stackOffset="expand" margin={{ top: 8, right: 8, bottom: 0, left: -12 }}
            barCategoryGap="18%">
            <CartesianGrid {...GRID} />
            <XAxis dataKey="day" tickFormatter={(d: string) => formatDay(d)} tick={AXIS_TICK}
              tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={24} />
            <YAxis tickFormatter={(v: number) => formatPercent(v)} tick={AXIS_TICK} tickLine={false}
              axisLine={false} width={48} />
            <Tooltip content={SentimentTip} cursor={{ fill: "var(--hover-wash)" }} />
            {(["negative", "neutral", "positive"] as const).map((key, i) => (
              <Bar key={key} dataKey={key} stackId="s" fill={`var(--sent-${key})`}
                stroke="var(--surface)" strokeWidth={1} maxBarSize={24}
                radius={i === 2 ? [4, 4, 0, 0] : 0} isAnimationActive={!still} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

// ---------------------------------------------------------------------------------------------
// Tone trend: mean score and its 7-day average around a zero baseline
// ---------------------------------------------------------------------------------------------
const ToneTip = makeTooltip<SentimentPoint>(
  (d) => formatDay(d.day, true),
  (d) => [
    { label: t("Daily mean"), value: formatScore(d.average), color: "var(--series-muted)" },
    { label: t("7-day mean"), value: formatScore(d.ma7), color: "var(--series-1)" },
  ],
);

export function ToneChart({ data, height = 220 }: { data: SentimentPoint[]; height?: number }) {
  const still = useReducedMotion();
  const extent = Math.max(0.2, ...data.map((d) => Math.abs(d.average ?? 0)));
  const bound = Math.min(1, Math.ceil(extent * 10) / 10);
  const last = [...data].reverse().find((d) => d.ma7 !== null);
  return (
    <figure className="chart-figure">
      <Legend
        items={[
          { label: t("Daily mean tone"), color: "var(--series-muted)", kind: "line" },
          { label: t("7-day mean"), color: "var(--series-1)", kind: "line" },
        ]}
      />
      <div role="img" aria-label={t("Mean tone from −1 (negative) to +1 (positive). Latest 7-day mean {score}.", { score: formatScore(last?.ma7) })}>
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="day" tickFormatter={(d: string) => formatDay(d)} tick={AXIS_TICK}
              tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={24} />
            <YAxis domain={[-bound, bound]} tickFormatter={(v: number) => formatScore(v)} tick={AXIS_TICK}
              tickLine={false} axisLine={false} width={48} />
            <ReferenceLine y={0} stroke="var(--axis)" />
            <Tooltip content={ToneTip} cursor={{ stroke: "var(--axis)" }} />
            <Line dataKey="average" stroke="var(--series-muted)" strokeWidth={2} dot={false}
              connectNulls isAnimationActive={!still} />
            <Line dataKey="ma7" stroke="var(--series-1)" strokeWidth={2} dot={false}
              activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} connectNulls
              isAnimationActive={!still} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

// ---------------------------------------------------------------------------------------------
// Diverging bars around zero (topic momentum)
// ---------------------------------------------------------------------------------------------
export interface DivergingDatum {
  label: string;
  value: number;
  detail: string;
}

const DivergingTip = makeTooltip<DivergingDatum>(
  (d) => d.label,
  (d) => [{ label: t("Change"), value: formatChange(d.value),
            color: d.value >= 0 ? "var(--div-pos)" : "var(--div-neg)" },
          { label: t("Articles"), value: d.detail, color: "transparent" }],
);

export function DivergingBars({ data, label }: { data: DivergingDatum[]; label: string }) {
  const still = useReducedMotion();
  const height = Math.max(160, data.length * 30 + 40);
  // Symmetric, rounded bound so zero sits in the middle and ticks are clean (±50%, ±100%, …).
  const raw = Math.max(0.5, ...data.map((d) => Math.abs(d.value)));
  const max = Math.ceil(raw * 2) / 2;
  const ticks = [-max, -max / 2, 0, max / 2, max];
  return (
    <div role="img" aria-label={label}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}
          barCategoryGap="28%">
          <CartesianGrid stroke="var(--grid)" horizontal={false} />
          <XAxis type="number" domain={[-max, max]} ticks={ticks} tickFormatter={(v: number) => formatChange(v)}
            tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: "var(--axis)" }} />
          <YAxis type="category" dataKey="label" width={150} tick={{ ...AXIS_TICK, fill: "var(--ink-2)" }}
            tickLine={false} axisLine={false} />
          <ReferenceLine x={0} stroke="var(--axis)" />
          <Tooltip content={DivergingTip} cursor={{ fill: "var(--hover-wash)" }} />
          <Bar
            dataKey="value"
            maxBarSize={18}
            isAnimationActive={!still}
            // 4px rounded data-end, square at the zero baseline: right end for gains, left for losses.
            shape={(props: unknown) => {
              const p = props as { x: number; y: number; width: number; height: number; payload: DivergingDatum };
              const up = p.payload.value >= 0;
              return (
                <Rectangle x={p.x} y={p.y} width={p.width} height={p.height}
                  fill={up ? "var(--div-pos)" : "var(--div-neg)"} radius={up ? [0, 4, 4, 0] : [4, 0, 0, 4]} />
              );
            }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Single-series daily line (entity / topic detail)
// ---------------------------------------------------------------------------------------------
export function DailyLine({ data, dataKey, label, height = 200 }: {
  data: { day: string; [k: string]: number | string | null }[];
  dataKey: string;
  label: string;
  height?: number;
}) {
  const still = useReducedMotion();
  const Tip = makeTooltip<Record<string, number | string | null>>(
    (d) => formatDay(String(d.day), true),
    (d) => [{ label, value: formatInt(Number(d[dataKey] ?? 0)), color: "var(--series-1)" }],
  );
  const total = data.reduce((s, d) => s + Number(d[dataKey] ?? 0), 0);
  return (
    <div role="img" aria-label={t("{label} per day: {total} in total over {days} days.", { label, total: formatInt(total), days: data.length })}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="day" tickFormatter={(d: string) => formatDay(d)} tick={AXIS_TICK}
            tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={24} />
          <YAxis allowDecimals={false} tick={AXIS_TICK} tickLine={false} axisLine={false} width={40} />
          <Tooltip content={Tip} cursor={{ fill: "var(--hover-wash)" }} />
          <Bar dataKey={dataKey} fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={24}
            isAnimationActive={!still} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// HTML primitives (no SVG needed): ranked bars and inline sentiment bars
// ---------------------------------------------------------------------------------------------
export function SentimentBar({ negative, neutral, positive }: {
  negative: number;
  neutral: number;
  positive: number;
}) {
  const total = negative + neutral + positive;
  if (!total) return <span className="rank-meta">—</span>;
  const parts = [
    { key: "negative", n: negative, color: "var(--sent-negative)" },
    { key: "neutral", n: neutral, color: "var(--sent-neutral)" },
    { key: "positive", n: positive, color: "var(--sent-positive)" },
  ];
  const summary = t("{n} negative, {u} neutral, {p} positive", {
    n: formatPercent(negative / total), u: formatPercent(neutral / total), p: formatPercent(positive / total),
  });
  return (
    <span className="tone-bar" role="img" aria-label={summary} title={summary}>
      {parts.map((p) =>
        p.n > 0 ? (
          <span key={p.key} style={{ flexGrow: p.n, background: p.color }} />
        ) : null,
      )}
    </span>
  );
}
