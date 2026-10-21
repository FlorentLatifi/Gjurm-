import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId, useRef } from "react";
import { Link } from "react-router-dom";

import type { StorySummary } from "@/shared/api/types";
import { formatRelative, summaryFor } from "@/shared/lib/format";
import {
  BIAS_GROUP_COLOR,
  BIAS_LABEL,
  biasGroup,
  blindspotLabel,
  countryLabel,
  leadingSegment,
  type Lens,
  segments,
} from "@/shared/model/ratings";
import { storyQuery } from "./api";
import { CoverageLine, StoryCoverage } from "./StoryCoverage";
import "./stories.css";
import { localName, t, tn } from "@/shared/i18n";

export function initials(name: string): string {
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
  // A story can be listed twice on one page (the lead and its section), so the heading id is per card.
  const titleId = useId();
  const summary = summaryFor(story);
  return (
    <article
      className={`story-card ${compact ? "story-card--compact" : ""} ${lead ? "story-card--lead" : ""}`}
      aria-labelledby={titleId}
    >
      <div className="story-card__top">
        {story.topic_name && <span className="kicker">{localName(story.topic_name, story.topic_name_sq)}</span>}
        <span>· <time dateTime={story.last_published_at}>{t("Updated {when}", { when: formatRelative(story.last_published_at) })}</time></span>
        <BlindspotBadges story={story} />
      </div>
      <h3 className="story-card__title" id={titleId} lang={story.language}>
        <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
      </h3>
      {!compact && summary && <p className="story-card__summary" lang={summary.lang}>{summary.text}</p>}
      <StoryCoverage coverage={story.coverage} lens={lens} size={compact ? "sm" : "md"} />
      <div className="story-card__foot">
        <SourceDots sources={story.sources} />
        <span>
          <strong>{tn(story.source_count, "{n} outlet", "{n} outlets")}</strong>
          {story.article_count > story.source_count && <> · {tn(story.article_count, "{n} article", "{n} articles")}</>}
        </span>
        {story.source_count > 1 && <span>{t("First: {outlet}", { outlet: story.first_source_name })}</span>}
      </div>
    </article>
  );
}

// ------------------------------------------------------------------------------------------
// The Ground News front page (ADR-028)
// ------------------------------------------------------------------------------------------

/** One of four dark cover tones, fixed per topic, so a topic always looks the same. */
function coverTone(slug: string | null): number {
  let h = 0;
  for (const ch of slug ?? "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return (h % 4) + 1;
}

/**
 * A story's picture, without a picture: GJURMË shows no publisher images (ADR-003), so where
 * Ground News has a photo there is a dark panel lettered with the story's topic and the outlets
 * that covered it.
 */
export function Cover({ story, children, className = "" }: { story: StorySummary; children?: ReactNode; className?: string }) {
  const topic = story.topic_name ? localName(story.topic_name, story.topic_name_sq) : t("News");
  return (
    <div className={`cover cover--${coverTone(story.topic_slug)} ${className}`}>
      {/* drawn by CSS from the attribute: a texture, not text to read (its name is in the kicker) */}
      <span className="cover__word" data-word={topic} aria-hidden="true" />
      <span className="cover__outlets" aria-hidden="true">
        {story.sources.slice(0, 4).map((src) => <span key={src.slug}>{initials(src.name)}</span>)}
        {story.source_count > 4 && <span>+{story.source_count - 4}</span>}
      </span>
      {children}
    </div>
  );
}

function kicker(story: StorySummary): string {
  return [story.topic_name && localName(story.topic_name, story.topic_name_sq), story.first_source_name]
    .filter(Boolean)
    .join(" · ");
}

/** The lead story: its cover full width, the headline on it, and the bar with its labels on it. */
export function HeroStory({ story, lens }: { story: StorySummary; lens: Lens }) {
  const prefetch = usePrefetchStory(story.id);
  const titleId = useId();
  return (
    <article className="story-card story-hero" aria-labelledby={titleId}>
      <Cover story={story} className="story-hero__cover">
        <div className="story-hero__body">
          <p className="story-hero__kicker">
            {kicker(story)} · <time dateTime={story.last_published_at}>{t("Updated {when}", { when: formatRelative(story.last_published_at) })}</time>
          </p>
          <p className="story-hero__count">
            {tn(story.source_count, "{n} outlet", "{n} outlets")} · {tn(story.article_count, "{n} article", "{n} articles")}
          </p>
          <h3 className="story-card__title" id={titleId} lang={story.language}>
            <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
          </h3>
          <StoryCoverage coverage={story.coverage} lens={lens} size="lg" labels={lens === "perspective" ? "inside" : "nonzero"} />
        </div>
      </Cover>
      <BlindspotBadges story={story} />
    </article>
  );
}

/** A row of the feed: kicker, headline and the one-line coverage, the cover on the right. */
export function StoryRow({ story, lens }: { story: StorySummary; lens: Lens }) {
  const prefetch = usePrefetchStory(story.id);
  const titleId = useId();
  return (
    <article className="story-card story-row" aria-labelledby={titleId}>
      <div className="story-row__text">
        <p className="story-row__kicker">{kicker(story)}</p>
        <h3 className="story-card__title" id={titleId} lang={story.language}>
          <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
        </h3>
        <CoverageLine coverage={story.coverage} lens={lens} sources={story.source_count} />
        {story.blindspots.length > 0 && <p className="story-row__badges"><BlindspotBadges story={story} /></p>}
      </div>
      <Cover story={story} className="story-row__cover" />
    </article>
  );
}

/** A headline and its one-line coverage, for the side columns ("Top news stories"). */
export function StoryLine({ story, lens }: { story: StorySummary; lens: Lens }) {
  const prefetch = usePrefetchStory(story.id);
  const titleId = useId();
  return (
    <article className="story-card story-line" aria-labelledby={titleId}>
      <h3 className="story-card__title" id={titleId} lang={story.language}>
        <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
      </h3>
      <CoverageLine coverage={story.coverage} lens={lens} sources={story.source_count} />
    </article>
  );
}

/** A blindspot, framed in the colour of the side that did cover it, as on Ground News. */
export function BlindspotCard({ story, lens }: { story: StorySummary; lens: Lens }) {
  const prefetch = usePrefetchStory(story.id);
  const titleId = useId();
  const lead = leadingSegment(segments(story.coverage, lens));
  return (
    <article className="story-card blindspot-card" aria-labelledby={titleId}
      style={{ ["--frame" as string]: lead && lens === "perspective" ? lead.segment.color : "var(--ink)" }}>
      <Cover story={story} className="blindspot-card__cover" />
      <div className="blindspot-card__body">
        <p className="blindspot-card__tags">
          <span className="tag tag--blindspot">{t("Blindspot")}</span>
          <span className="tag">{tn(story.source_count, "{n} outlet", "{n} outlets")}</span>
        </p>
        <h3 className="story-card__title" id={titleId} lang={story.language}>
          <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
        </h3>
        <p className="blindspot-card__why"><BlindspotBadges story={story} /></p>
        <StoryCoverage coverage={story.coverage} lens={lens} size="lg" labels={lens === "perspective" ? "inside" : "nonzero"} />
      </div>
    </article>
  );
}
