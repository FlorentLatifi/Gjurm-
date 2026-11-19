import { useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import type { StorySummary } from "@/shared/api/types";
import { formatRelative, summaryFor } from "@/shared/lib/format";
import { blindspotLabel, type Lens } from "@/shared/model/ratings";
import { storyQuery } from "./api";
import { COVER_SIZES, outletSizes } from "./photoSizes";
import { coverageCounts, StoryCoverage } from "./StoryCoverage";
import "./stories.css";
import { localName, t, tn } from "@/shared/i18n";

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

/** "8 outlets  ·  2 Left · 5 Center · 1 Right  ·  2 hours ago": a story's coverage in one line. */
function CoverageLine({ story, lens }: { story: StorySummary; lens: Lens }) {
  return (
    <p className="story-line">
      <strong>{tn(story.source_count, "{n} outlet", "{n} outlets")}</strong>
      <span>{coverageCounts(story.coverage, lens)}</span>
      <time dateTime={story.last_published_at}>{formatRelative(story.last_published_at)}</time>
    </p>
  );
}

/**
 * One story in a list: topic and time, the representative headline (links to the story page,
 * which links every outlet's original), the coverage bar, and who covered it first. `compact`
 * is the short form for related stories and side columns: the bar and one line under it.
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
        {!compact && <time dateTime={story.last_published_at}>{t("Updated {when}", { when: formatRelative(story.last_published_at) })}</time>}
      </div>
      <h3 className="story-card__title" id={titleId} lang={story.language}>
        <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
      </h3>
      {!compact && summary && <p className="story-card__summary" lang={summary.lang}>{summary.text}</p>}
      <StoryCoverage coverage={story.coverage} lens={lens} size={compact ? "sm" : "md"}
        labels={compact ? "none" : undefined} missing={story.blindspots} />
      {compact ? (
        <CoverageLine story={story} lens={lens} />
      ) : (
        <div className="story-card__foot">
          <span>
            <strong>{tn(story.source_count, "{n} outlet", "{n} outlets")}</strong>
            {story.article_count > story.source_count && <> · {tn(story.article_count, "{n} article", "{n} articles")}</>}
          </span>
          {story.source_count > 1 && story.first_source_name && <span>{t("First: {outlet}", { outlet: story.first_source_name })}</span>}
        </div>
      )}
      {story.blindspots.length > 0 && <p className="story-card__badges"><BlindspotBadges story={story} /></p>}
    </article>
  );
}

// ------------------------------------------------------------------------------------------
// The front page (ADR-032)
// ------------------------------------------------------------------------------------------

/**
 * A story's picture: the photo an outlet put in its own feed entry, loaded from the outlet's
 * site and never copied (ADR-030). Where the outlet's server has smaller sizes of it, the browser
 * picks the one the box needs (photoSizes.ts); if that fails, the feed's own address is tried. A
 * story without a photo — or whose photo fails to load — is set in type alone, as a paper sets
 * most of its stories.
 */
export function Cover({ story, className = "", sizes }: { story: StorySummary; className?: string; sizes: string }) {
  // what failed for which photo: the outlet's sizes (try the feed's address), or the photo itself
  const [failed, setFailed] = useState<{ photo: string; all: boolean } | null>(null);
  const photo = story.image_url;
  const tried = failed?.photo === photo ? failed : null;
  if (!photo || tried?.all) return null;
  const srcSet = tried ? undefined : outletSizes(photo);
  return (
    <div className={`cover ${className}`}>
      {/* decorative: the headline beside it says what the story is */}
      <img key={srcSet ? "sizes" : "feed"} className="cover__photo" srcSet={srcSet} sizes={srcSet && sizes} src={photo}
        alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer"
        onError={() => setFailed({ photo, all: !srcSet })} />
    </div>
  );
}

function topicOf(story: StorySummary): string | null {
  return story.topic_name ? localName(story.topic_name, story.topic_name_sq) : null;
}

/** The lead story: the headline across the column, its summary and coverage beside its photo. */
export function HeroStory({ story, lens }: { story: StorySummary; lens: Lens }) {
  const prefetch = usePrefetchStory(story.id);
  const titleId = useId();
  const summary = summaryFor(story);
  const topic = topicOf(story);
  return (
    <article className="story-card story-hero" aria-labelledby={titleId}>
      <p className="story-hero__kicker">
        {topic && <span className="kicker">{topic}</span>}
        <time dateTime={story.last_published_at}>{t("Updated {when}", { when: formatRelative(story.last_published_at) })}</time>
      </p>
      <h3 className="story-card__title" id={titleId} lang={story.language}>
        <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
      </h3>
      <div className="story-hero__text">
        {summary && <p className="story-hero__summary" lang={summary.lang}>{summary.text}</p>}
        <StoryCoverage coverage={story.coverage} lens={lens} size="lg" missing={story.blindspots} />
        <p className="story-hero__meta">
          <strong className="story-hero__count">
            {tn(story.source_count, "{n} outlet", "{n} outlets")} · {tn(story.article_count, "{n} article", "{n} articles")}
          </strong>
          {story.source_count > 1 && story.first_source_name && <span>{t("First: {outlet}", { outlet: story.first_source_name })}</span>}
        </p>
        {story.blindspots.length > 0 && <p className="story-card__badges"><BlindspotBadges story={story} /></p>}
      </div>
      <Cover story={story} className="story-hero__cover" sizes={COVER_SIZES.hero} />
    </article>
  );
}

/** A story of the feed: kicker, headline, its photo when it has one, the bar and one line. */
export function StoryRow({ story, lens }: { story: StorySummary; lens: Lens }) {
  const prefetch = usePrefetchStory(story.id);
  const titleId = useId();
  const topic = topicOf(story);
  return (
    <article className="story-card story-row" aria-labelledby={titleId}>
      <div className="story-row__head">
        {topic && <p className="kicker">{topic}</p>}
        <h3 className="story-card__title" id={titleId} lang={story.language}>
          <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
        </h3>
      </div>
      <Cover story={story} className="story-row__cover" sizes={COVER_SIZES.row} />
      <div className="story-row__cov">
        <StoryCoverage coverage={story.coverage} lens={lens} size="sm" labels="none" missing={story.blindspots} />
        <CoverageLine story={story} lens={lens} />
      </div>
      {story.blindspots.length > 0 && <p className="story-card__badges"><BlindspotBadges story={story} /></p>}
    </article>
  );
}

/** A headline and its one line of coverage, for the side column. */
export function StoryLine({ story, lens }: { story: StorySummary; lens: Lens }) {
  const prefetch = usePrefetchStory(story.id);
  const titleId = useId();
  return (
    <article className="story-card story-brief" aria-labelledby={titleId}>
      <h3 className="story-card__title" id={titleId} lang={story.language}>
        <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
      </h3>
      <CoverageLine story={story} lens={lens} />
    </article>
  );
}

/** A blindspot: what is missing first, then the headline and a bar with the missing side left empty. */
export function BlindspotCard({ story, lens }: { story: StorySummary; lens: Lens }) {
  const prefetch = usePrefetchStory(story.id);
  const titleId = useId();
  return (
    <article className="story-card blindspot-card" aria-labelledby={titleId}>
      <p className="story-card__badges"><BlindspotBadges story={story} /></p>
      <h3 className="story-card__title" id={titleId} lang={story.language}>
        <Link to={`/stories/${story.id}`} {...prefetch}>{story.title}</Link>
      </h3>
      <StoryCoverage coverage={story.coverage} lens={lens} size="sm" labels="none" missing={story.blindspots} />
      <CoverageLine story={story} lens={lens} />
    </article>
  );
}
