/**
 * Contract check, compiled by `npm run typecheck` and never bundled (nothing imports it).
 *
 * types.ts is written by hand — narrower unions, comments — and the app reads only those. This
 * file asserts that what the API *declares* (schema.gen.ts, generated from the backend's OpenAPI
 * schema in openapi.json) fits what the app expects: a renamed or removed field, or a changed
 * type, fails the typecheck with the exact property named. Regenerate with `npm run api:types`.
 */
import type * as T from "./types";
import type { components } from "./schema.gen";

type S = components["schemas"];
declare const api: { [K in keyof S]: S[K] };

export const AnalysisMode: T.AnalysisMode = api.AnalysisMode;
export const ArticleDetail: T.ArticleDetail = api.ArticleDetail;
export const ArticleSummary: T.ArticleSummary = api.ArticleSummary;
export const Blindspot: T.Blindspot = api.Blindspot;
export const Blindspots: T.Blindspots = api.Blindspots;
export const CoOccurrence: T.CoOccurrence = api.CoOccurrence;
export const Coverage: T.Coverage = api.Coverage;
export const DateRange: T.DateRange = api.DateRange;
export const EntityDetail: T.EntityDetail = api.EntityDetail;
export const EntityRef: T.EntityRef = api.EntityRef;
export const EntitySpike: T.EntitySpike = api.EntitySpike;
export const EntitySpikes: T.EntitySpikes = api.EntitySpikes;
export const EntityStat: T.EntityStat = api.EntityStat;
export const Overview: T.Overview = api.Overview;
export const PublicStatus: T.PublicStatus = api.PublicStatus;
export const SentimentGroup: T.SentimentGroup = api.SentimentGroup;
export const SentimentGroups: T.SentimentGroups = api.SentimentGroups;
export const SentimentPoint: T.SentimentPoint = api.SentimentPoint;
export const SentimentSeries: T.SentimentSeries = api.SentimentSeries;
export const SentimentShift: T.SentimentShift = api.SentimentShift;
export const SourceProfile: T.SourceProfile = api.SourceProfile;
export const SourceStat: T.SourceStat = api.SourceStat;
export const StoryArticle: T.StoryArticle = api.StoryArticle;
export const StoryDetail: T.StoryDetail = api.StoryDetail;
export const StorySummary: T.StorySummary = api.StorySummary;
export const TaxonomyTopic: T.TaxonomyTopic = api.TaxonomyTopic;
export const TopicDetail: T.TopicDetail = api.TopicDetail;
export const TopicMomentum: T.TopicMomentum = api.TopicMomentum;
export const TopicStat: T.TopicStat = api.TopicStat;
export const VolumePoint: T.VolumePoint = api.VolumePoint;
export const VolumeSeries: T.VolumeSeries = api.VolumeSeries;
export const Page_ArticleSummary_: T.Page<T.ArticleSummary> = api.Page_ArticleSummary_;
export const Page_StorySummary_: T.Page<T.StorySummary> = api.Page_StorySummary_;
