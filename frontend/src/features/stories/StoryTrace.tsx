import type { StoryDetail } from "@/shared/api/types";
import { formatDateTime } from "@/shared/lib/format";
import type { Lens } from "@/shared/model/ratings";

import { groupOf, markColor, segmentsByKey } from "./lensGroup";

function span(ms: number): string {
  const h = ms / 3_600_000;
  if (h < 1) return `${Math.max(1, Math.round(ms / 60_000))} min`;
  if (h < 48) return `${Math.round(h)} h`;
  return `${Math.round(h / 24)} days`;
}

/**
 * The trace: every report of the story as one tick on a single time line, coloured by the
 * current lens, the first report marked taller. GJURMË means "trace" — this is who left a mark on
 * the story, and when. The ordered list below it carries the same facts for screen readers, so
 * the drawing is one labelled image.
 */
export function StoryTrace({ story, lens }: { story: StoryDetail; lens: Lens }) {
  const times = story.articles.map((a) => Date.parse(a.published_at));
  const start = Math.min(...times);
  const end = Math.max(...times);
  const width = end - start;
  const segs = segmentsByKey(story.coverage, lens);
  const first = story.articles.find((a) => a.is_first) ?? story.articles[0]!;
  const present = [...new Set(story.articles.map((a) => groupOf(a, lens)))]
    .map((k) => segs.get(k))
    .filter((s) => s !== undefined);
  const label =
    `${story.articles.length} reports from ${story.source_count} outlets over ${span(width)}, ` +
    `first by ${first.source_name} at ${formatDateTime(first.published_at)}.`;

  return (
    <div className="trace">
      <div className="trace__track" role="img" aria-label={label}>
        {story.articles.map((a, i) => {
          const seg = segs.get(groupOf(a, lens));
          const x = width > 0 ? ((times[i]! - start) / width) * 100 : 50;
          return (
            <span
              key={a.id}
              className={`trace__tick ${a.id === first.id ? "trace__tick--first" : ""}`}
              style={{ left: `${x}%`, ["--tick" as string]: markColor(seg) }}
              title={`${a.source_name} · ${formatDateTime(a.published_at)}${seg ? ` · ${seg.label}` : ""}`}
            />
          );
        })}
      </div>
      <div className="trace__axis" aria-hidden="true">
        <time dateTime={new Date(start).toISOString()}>{formatDateTime(new Date(start).toISOString())}</time>
        <span className="trace__span">{span(width)}</span>
        <time dateTime={new Date(end).toISOString()}>{formatDateTime(new Date(end).toISOString())}</time>
      </div>
      <div className="trace__legend" aria-hidden="true">
        {present.map((s) => (
          <span key={s.key}>
            <i style={{ ["--tick" as string]: markColor(s) }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
