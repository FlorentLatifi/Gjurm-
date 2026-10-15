import { useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { Link } from "react-router-dom";

import type { StorySummary } from "@/shared/api/types";
import { formatRelative, realSummary } from "@/shared/lib/format";
import {
  BIAS_GROUP_COLOR,
  BIAS_LABEL,
  biasGroup,
  blindspotLabel,
  countryLabel,
  type Lens,
} from "@/shared/model/ratings";
import { storyQuery } from "./api";
import { StoryCoverage } from "./StoryCoverage";
import "./stories.css";

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

/** The story page's code; the router lazy-loads the same module. */
export const loadStoryPage = () => import("./pages/Story");

/**
 * Starts loading a story (its data and the page's code) when the reader shows intent: focus at
 * once, hover after a short pause so sweeping the pointer across the feed fetches nothing.
 */
function usePrefetchStory(id: number) {
  const client = useQueryClient();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const start = () => {
    void client.prefetchQuery(storyQuery(id));
    void loadStoryPage();
  };
  return {
    onFocus: start,
    onPointerEnter: () => {
      clearTimeout(timer.current);
      timer.current = setTimeout(start, 120);
    },
    onPointerLeave: () => clearTimeout(timer.current),
  };
}

/**
 * One story in a feed: topic and time, the representative headline (links to the story page,
 * which links every outlet's original), the coverage bar, and who covered it first.
 */
export function StoryCard({
  story,
  lens,
  compact = false,
  lead = false,
}: {
  story: StorySummary;
  lens: Lens;
  compact?: boolean;
  /** The day's most covered story, set larger at the top of the feed. */
  lead?: boolean;
}) {
  const prefetch = usePrefetchStory(story.id);
  return (
    <article
      className={`story-card ${compact ? "story-card--compact" : ""} ${lead ? "story-card--lead" : ""}`}
      aria-labelledby={`story-${story.id}`}
    >
      <div className="story-card__top">
        {story.topic_name && <span className="kicker">{story.topic_name}</span>}
        <span>· <time dateTime={story.last_published_at}>Updated {formatRelative(story.last_published_at)}</time></span>
        <BlindspotBadges story={story} />
      </div>
      <h3 className="story-card__title" id={`story-${story.id}`} lang={story.language}>
        <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
      </h3>
      {!compact && realSummary(story.summary_en) && (
        <p className="story-card__summary">{realSummary(story.summary_en)}</p>
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
