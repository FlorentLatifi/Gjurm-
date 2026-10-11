import { Link } from "react-router-dom";

import type { StorySummary } from "@/shared/api/types";
import { formatRelative } from "@/shared/lib/format";
import { BIAS_GROUP_COLOR, BIAS_LABEL, biasGroup, blindspotLabel, countryLabel, type Lens } from "@/shared/model/ratings";
import { StoryCoverage } from "./StoryCoverage";

function initials(name: string): string {
  const words = name.replace(/[^\p{L}\p{N} ]/gu, "").split(/\s+/).filter(Boolean);
  return ((words[0]?.[0] ?? "") + (words[1]?.[0] ?? "")).toUpperCase() || "?";
}

/** Small round badges for the outlets that covered a story; the underline is the outlet's perspective. */
export function SourceDots({ sources, max = 6 }: { sources: StorySummary["sources"]; max?: number }) {
  const shown = sources.slice(0, max);
  return (
    <span className="source-dots" aria-hidden="true">
      {shown.map((s) => (
        <span key={s.slug} className="source-dot" title={`${s.name} · ${BIAS_LABEL[s.bias]} · ${countryLabel(s.country)}`}
          style={{ ["--dot-bias" as string]: BIAS_GROUP_COLOR[biasGroup(s.bias)] }}>
          {initials(s.name)}
        </span>
      ))}
      {sources.length > max && <span className="source-dot">+{sources.length - max}</span>}
    </span>
  );
}

export function BlindspotBadges({ story }: { story: StorySummary }) {
  return (
    <>
      {story.blindspots.map((b) => (
        <span key={`${b.kind}-${b.missing}`} className="badge badge--blindspot">
          {blindspotLabel(b)}
        </span>
      ))}
    </>
  );
}

/**
 * One story in a feed: topic and time, the representative headline (links to the story page,
 * which links every outlet's original), the coverage bar, and who covered it first.
 */
export function StoryCard({ story, lens, compact = false }: { story: StorySummary; lens: Lens; compact?: boolean }) {
  return (
    <article className={`card story-card ${compact ? "story-card--compact" : ""}`} aria-labelledby={`story-${story.id}`}>
      <div className="story-card__top">
        {story.topic_name && <span>{story.topic_name}</span>}
        <span>· <time dateTime={story.last_published_at}>Updated {formatRelative(story.last_published_at)}</time></span>
        <BlindspotBadges story={story} />
      </div>
      <h3 className="story-card__title" id={`story-${story.id}`} lang={story.language}>
        <Link to={`/stories/${story.id}`}>{story.title}</Link>
      </h3>
      {!compact && story.summary_en && !story.summary_en.startsWith("[headline") && (
        <p className="story-card__summary">{story.summary_en}</p>
      )}
      <StoryCoverage coverage={story.coverage} lens={lens} size={compact ? "sm" : "md"} />
      <div className="story-card__foot">
        <SourceDots sources={story.sources} />
        <span>
          <strong>{story.source_count} {story.source_count === 1 ? "outlet" : "outlets"}</strong>
          {story.article_count > story.source_count && <> · {story.article_count} articles</>}
        </span>
        {story.source_count > 1 && <span>First: {story.first_source_name}</span>}
      </div>
    </article>
  );
}
