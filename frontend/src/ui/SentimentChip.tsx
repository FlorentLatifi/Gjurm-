import type { SentimentLabel } from "@/shared/api/types";

const SENTIMENT_COLOR: Record<SentimentLabel, string> = {
  negative: "var(--sent-negative)",
  neutral: "var(--sent-neutral)",
  positive: "var(--sent-positive)",
};

export function SentimentChip({ label }: { label: SentimentLabel | null }) {
  if (!label) return null;
  return (
    <span className="chip">
      <span className="dot" style={{ background: SENTIMENT_COLOR[label] }} aria-hidden="true" />
      <span>{label[0]!.toUpperCase() + label.slice(1)} tone</span>
    </span>
  );
}
