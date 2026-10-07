# Sources

Every source is declared in `backend/src/gjurme/sources/sources.yaml`. Nothing about a feed is assumed: a source is enabled only after the validator has fetched it from the open internet and confirmed a working, robots-permitted feed with the fields the pipeline needs.

## Current registry (validated 2026-09-24, extended 2026-10-05)

Validation ran on GitHub's runners, because the build container's egress policy blocks news domains: [Source validation run #2](https://github.com/FlorentLatifi/Gjurm-/actions/runs/36046867715) (`validate` job: feed check and autodiscovery; `live-pipeline` job: real ingest → process → enrich → quality).

| Source | Country / lang | Feed | Status | Evidence |
|---|---|---|---|---|
| Telegrafi | XK / sq | `https://telegrafi.com/feed/` | **enabled** | RSS 2.0, 30 items; title / link / date present on 100% |
| KOHA | XK / sq | `https://www.koha.net/rss` | **enabled** | 20 items; fields 100% |
| Gazeta Express | XK / sq | `https://www.gazetaexpress.com/feed/` | **enabled** | 10 items (short window, so it needs frequent polling). The XML is not well-formed; feedparser recovers it and the fetch is flagged `malformed` in `raw.feed_fetches`. |
| Kallxo (BIRN Kosovo) | XK / sq | `https://kallxo.com/feed/` | **enabled** | 11 items; investigative / justice |
| Radio Evropa e Lirë (RFE/RL) | XK / sq | `https://www.evropaelire.org/api/` | **enabled** | The declared `/rssfeeds` page is not a feed; the validator's **autodiscovery** found the feed (20 items) |
| Top Channel | AL / sq | `https://top-channel.tv/feed/` | **excluded** | HTTP 403 to automated requests. Not circumvented. |
| Balkan Insight | regional / en | `https://balkaninsight.com/feed/` | **excluded** | `robots.txt` disallows the feed path for generic agents. Respected. |
| Reporter.al (BIRN Albania) | AL / sq | `https://www.reporter.al/feed/` | **enabled** | 10 items; fields 100% (2026-09-28 and 2026-10-05) |
| Euronews Albania | AL / sq | `https://euronews.al/feed/` | **enabled** | 10 items; fields 100% (both runs) |
| BalkanWeb | AL / sq | `https://www.balkanweb.com/feed/` | **enabled** | 10 items; fields 100% (both runs) |
| Portalb.mk | MK / sq | `https://portalb.mk/feed/` | **enabled** | 10 items; fields 100% (both runs) |
| Reporteri.net | XK / sq | `https://reporteri.net/feed/` | **enabled** | 21 items; fields 100% (both runs) |
| A2 CNN | AL / sq | `https://a2news.com/feed/` | **excluded** | HTTP 404 in both runs; no other feed found |
| Kosovapress | XK / sq | `https://kosovapress.com/feed/` | **excluded** | HTTP 403 to automated requests, also on the autodiscovered `feed.kosovapress.com`. Not circumvented. |
| Prishtina Insight (BIRN) | XK / en | `https://prishtinainsight.com/feed/` | held back | Feed OK (5 items), but it is in English and the zero-cost keyword rules only understand Albanian. Enable once an AI model analyses articles. |

**Live run result** (same workflow, real feeds, heuristic enrichment because no API key is configured): 91 articles stored from the 5 enabled sources, 0 rejected items, Gazeta Express's malformed XML recovered, and 2 cross-outlet near-duplicates linked by dedup L4.

The five sources added on 2026-10-05 passed the weekly scheduled validation twice ([2026-09-28](https://github.com/FlorentLatifi/Gjurm-/actions/runs/36432792910), [2026-10-05](https://github.com/FlorentLatifi/Gjurm-/actions/runs/37327377828)). They bring Albania and North Macedonia in: 6 of the 10 enabled sources are Kosovo-based, 3 Albanian, 1 North Macedonian. Two of Albania's largest broadcasters (Top Channel, A2 CNN) still have no usable feed.

**Occasional 403s.** A source can answer 403 to one weekly check and 200 to the next: Gazeta Express did on 2026-09-28, Kallxo on 2026-10-05. That points to the publisher's protection reacting to GitHub's shared runner addresses rather than to a dead feed, so a single 403 does not disable a source. The server polls from its own address, and 20 consecutive failures there disable a source automatically.

## Adding or changing a source

1. Add an entry to `sources.yaml` with `enabled: false`:
   ```yaml
   - slug: example            # stable id, lower-case, used in URLs and filters
     name: Example News
     homepage_url: https://example.com/
     feed_url: https://example.com/feed/
     discovery_urls: [https://example.com/]   # scanned for <link rel="alternate"> if feed_url fails
     language: sq
     country: XK
     enabled: false
     notes: Candidate — why this source matters.
   ```
2. Validate it from a machine with open egress (a server, a laptop, or GitHub Actions: *Actions → Source validation → Run workflow*):
   ```bash
   gjurme sources validate --slug example                          # Markdown report to stdout
   gjurme sources validate --slug example --json report.json       # also write JSON
   gjurme sources validate --strict                                # exit 1 if an enabled source fails
   ```
   The report shows the HTTP status, content type, robots.txt verdict, feed format, item count, the share of items with title / link / date / summary, the date range, and any autodiscovered feed URLs.
3. If it passes, set `enabled: true`, put the validated URL in `feed_url`, add a dated note, and commit.
4. Apply it: `gjurme sources sync`. The `migrate` step of every deploy (`gjurme db upgrade`) also syncs, so merging the YAML change and deploying is enough. Syncing is idempotent: it inserts new sources and updates changed metadata. It never deletes a source or its articles; disabling is the removal mechanism.

## What the fetcher guarantees for every source

- An identifying `User-Agent` with a contact URL (`HTTP_USER_AGENT`, `CONTACT_URL`).
- `robots.txt` is checked for the feed path (RFC 9309 semantics; `RESPECT_ROBOTS_TXT=true`), and a disallow means no fetch.
- Conditional GET with `ETag` / `Last-Modified`, so an unchanged feed costs the publisher a 304.
- At most one fetch per 15 minutes per source (the scheduler interval), a 15 s timeout and a 5 MB response cap.
- Redirects are followed manually (max 5), and every hop's host must resolve to a public address (SSRF guard). Only `http`/`https`.
- Failures are isolated per source. After 20 consecutive failures the source is auto-disabled (`is_active = false`, `verification_status = failing`) and an alert asks the operator to check it.

The weekly schedule of the *Source validation* workflow re-checks every source, so a feed that moves or starts blocking shows up in the report even before the pipeline notices.
