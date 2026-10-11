# Frontend system architecture

**Status:** draft for review, not implemented. Written 2026-10-11 against branch head `2532da1`.
**Scope:** the React app in `frontend/` and how it is delivered (Vite build, Caddy). Backend only where it shapes the frontend.

Each section gives the current state (measured, not estimated), the target, the rules that keep the target in place, and the migration steps. Section 6 lists the root decisions to settle before any implementation file is written.

---

## 0. Baseline and audit findings

### What exists today

| | |
|---|---|
| Stack | React 19.3, React Router 7.18 (declarative `<Routes>`), TanStack Query 5, Recharts 3, Vite 8 (Rolldown), plain CSS |
| Source | 5.6k lines: `api/` (client, 1 hook per endpoint, 370 lines of hand-written types), `components/` (9 files), `lib/` (5), `pages/` (12 files, 17 routes), `styles/` (`tokens.css` 151 lines, `app.css` 961 lines) |
| Routing | every route is `React.lazy`; one `<Suspense>` at the root; **no error boundary** |
| State | server data in React Query (`staleTime` 60 s, `keepPreviousData`); filters in the URL (`useFilters`); 3 browser-stored preferences, each with its own hand-written pattern (theme: `useState` + effect; lens: `useState` per hook instance; reading history: `useSyncExternalStore` store) |
| Styling | semantic CSS variables, data palettes validated with the palette validator (ADR-011); one global stylesheet with BEM-style classes; system font stack |
| Tests | Vitest (35), Playwright + axe (62 = 31 scenarios × desktop/mobile) |

### Bundle (production build, gzip -9)

| Load | JS gz | Notes |
|---|---:|---|
| Entry closure (every page) | **95.2 KB** | `react` chunk 83.2 (react-dom, react-router, scheduler, react-redux*), `index` 15.1 (TanStack Query core + app shell), runtime 0.4 |
| CSS (every page) | 4.1 KB | one file, 15.9 KB raw |
| `/` Stories feed | +8.6 KB | **≈108 KB total**, no chart library |
| `/stories/:id`, `/blindspot`, `/my-news`, `/sources/:slug`, `/articles` | +5–9 KB each | |
| `/dashboard`, `/trends`, `/topics`, `/entities`, `/sources` | +109–112 KB each | Recharts chunk 106.9 KB is shared by all of them |

\* `react-redux` is used only by Recharts, but `manualChunks` matches `id.includes("node_modules/react")`, so it lands in the eagerly loaded `react` chunk. A stricter rule measured **−1.1 KB gz** on the critical path. This is real but small, so it is P2.

### Findings, ranked

| # | Severity | Finding | Evidence |
|---|---|---|---|
| F1 | **P0** | **A failed chunk load blanks the app.** There is no error boundary, so a rejected `import()` (offline, or an open tab after a deploy has removed the old hashed chunks) unmounts the whole tree. | `main.tsx`: one `<Suspense>`, no `ErrorBoundary`/`errorElement` anywhere in `src/` |
| F2 | **P0** | **Missing chunks are answered with `index.html` and cached for a year.** `try_files {path} /index.html` also covers `/assets/*`, so a missing chunk returns HTML with status 200, and `@hashed` marks that response `immutable, max-age=31536000`. A request that reaches the server during a deploy switchover can poison that chunk URL for that browser. | `frontend/Caddyfile`, `handle` block |
| F3 | P1 | **Deep links have no `Cache-Control`.** `@html` matches only `/` and `/index.html`. Caddy runs `header` before `try_files`, so `/stories/12` (served from `index.html`) gets no header and browsers cache it heuristically. That can serve stale HTML pointing at deleted chunks, which leads into F1. `/theme.js`, `/manifest.webmanifest` and the icons have the same gap. | `Caddyfile`; Caddy directive order |
| F4 | P1 | **The data request waits for the code (request waterfall).** A cold `/stories/12` goes HTML → entry JS → route chunk → only then `GET /api/v1/stories/12`. The API call could start at route match, in parallel with the chunk. | `useStory` runs inside the lazy page |
| F5 | P1 | **Brand accent = "Left".** Links, focus and active UI use `--accent` `#2a78d6`, which is also `--bias-left`, `--cat-1` (Albania) and the factuality ramp. On a product about bias, every link reads as left-leaning. | `tokens.css` |
| F6 | P1 | **No type, spacing or motion system.** 22 distinct `font-size` values, 8 weights (400/450/520/600/620/640/650/700), 61 distinct padding/gap/margin declarations, 76 inline `style={{}}` in TSX. Only colour is tokenised. | `grep` over `app.css` and `src/**/*.tsx` |
| F7 | P2 | **A keystroke re-renders the whole page.** Search-input state lives in the page component, so each keystroke re-renders the feed (15 `StoryCard`s plus the sidebar) on Stories, Articles and Entities. Cheap today, but it is the pattern that scales badly. | `Stories.tsx` `const [text, setText]` |
| F8 | P2 | **Every URL change re-renders the shell and lists.** `Layout` calls `useLocation()` (for focus management) and `ArticleList` calls `useFilters()` (only to build links), so both re-render on every search-param change. | `Layout.tsx`, `components/lists.tsx` |
| F9 | P2 | **Three persistence patterns for three preferences.** The lens preference is per hook instance, so two pickers on one page would disagree, and it does not sync across tabs. Reading history does sync. | `lib/reading.ts`, `Layout.tsx` |
| F10 | P2 | **API types are hand-mirrored** from the Pydantic schemas (370 lines). Drift is caught only by e2e tests. | `api/types.ts` |
| F11 | P2 | **Story links share the site-wide preview.** The SPA serves one `index.html`, so a story shared on social media shows the generic title and image. | `index.html` OG tags |

What is already right and should be kept: route-level splitting, charts kept off the home route, `keepPreviousData` with dimmed refetch, URL-owned filters, the Card loading, error and empty contract, the validated data palettes, and the reduced-motion and forced-colors handling.

---

## 1. Component boundaries and hierarchy

### Layers

Dependencies point one way, downward. A layer may import only from the layers below it.

```mermaid
flowchart TD
    APP["app/<br/>bootstrap · router · providers · shell · error boundary"]
    FEAT["features/*<br/>stateful blocks + pages per domain"]
    STORES["stores/<br/>Zustand: client-global state"]
    UI["ui/<br/>pure components: props in, markup out"]
    SHARED["shared/<br/>api client + types · pure lib · domain model"]
    DESIGN["design/<br/>tokens · fonts · base CSS"]
    APP --> FEAT
    APP --> UI
    FEAT --> STORES
    FEAT --> UI
    FEAT --> SHARED
    STORES --> SHARED
    UI --> SHARED
    UI --> DESIGN
    APP --> DESIGN
```

| Layer | Owns | May import | Must not |
|---|---|---|---|
| `design/` | CSS custom properties, `@font-face`, reset/base | nothing | contain selectors for components |
| `shared/` | `fetch` client, generated API types, pure functions (`format`, URL parsing), domain model (`ratings`: domain value → label and token name) | `design` (token *names* only) | import React Query, the router, stores, or React components |
| `ui/` | pure components: `Button`, `Segmented`, `Field`, `Badge`, `Card`, `States`, `StatTile`, `CoverageBar`, `RankList`, `charts/*` | `shared/lib`, `shared/model`, `design` | fetch data, call router hooks, read stores, know an endpoint exists |
| `stores/` | client-global state (Zustand) | `shared` | hold server data or anything the URL can hold |
| `features/<domain>/` | query options, stateful blocks (`StoryFeed`, `HeadlineColumns`), pages | `ui`, `shared`, `stores`, and **another feature's `index.ts` only** | deep-import another feature; create import cycles |
| `app/` | `main.tsx`, router table, `QueryClient`, shell (header/nav/footer), `ErrorBoundary`, route focus | everything | contain domain logic |

`ui/Card` keeps its structural `QueryLike` interface. It renders loading, error and empty states for any object of that shape without importing React Query. That decoupling already exists and is the model for the rest of `ui/`.

### Folder structure, mapped from today's files

```
frontend/src/
├── app/
│   ├── main.tsx                 ← main.tsx (bootstrap only)
│   ├── router.tsx               ← AppRoutes → createBrowserRouter route objects (lazy + loader)
│   ├── queryClient.ts           ← QueryClient defaults from main.tsx
│   ├── Shell.tsx                ← components/Layout.tsx (header, nav, footer)
│   ├── RouteFocus.tsx           ← focus/scroll effect split out of Layout (F8)
│   └── RouteError.tsx           ← NEW: errorElement + chunk-reload (F1)
├── design/
│   ├── tokens/
│   │   ├── color.css            ← tokens.css (chrome + data roles, light/dark)
│   │   ├── type.css             ← NEW scale (§4)
│   │   ├── space.css            ← NEW scale (§4)
│   │   └── motion.css           ← NEW durations/easings (§4)
│   ├── fonts/                   ← NEW self-hosted woff2 + @font-face
│   ├── base.css                 ← reset, body, headings, focus, skip link from app.css
│   └── index.css
├── shared/
│   ├── api/
│   │   ├── client.ts            ← api/client.ts (unchanged)
│   │   └── schema.gen.ts        ← NEW: generated from /api/openapi.json (F10); types.ts re-exports
│   ├── lib/                     ← format.ts, useTitle.ts, urlState.ts (← filters.ts)
│   └── model/ratings.ts         ← lib/ratings.ts
├── stores/
│   ├── preferences.ts           ← theme (Layout) + lens (reading.ts useLens)
│   └── reading.ts               ← reading history (reading.ts store)
├── ui/
│   ├── Button.tsx, Segmented.tsx, Field.tsx, Badge.tsx    ← NEW, extracted from repeated markup
│   ├── Card.tsx, States.tsx, StatTile.tsx                 ← components/
│   ├── CoverageBar.tsx          ← CoverageBar only (segments in)
│   ├── RankList.tsx             ← lists.tsx, hrefs passed in instead of useFilters (F8)
│   └── charts/                  ← components/charts.tsx (only ever reached through lazy routes)
└── features/
    ├── stories/   api.ts · StoryCard · SourceDots · BlindspotBadges · LensPicker · StoryCoverage
    │              · SearchField · pages/{Feed, Story, Blindspot}.tsx · index.ts
    ├── sources/   api.ts · pages/{Sources, SourceProfile}.tsx · index.ts
    ├── reading/   pages/MyNews.tsx (readingCoverage, missingSide) · index.ts
    ├── analytics/ api.ts · pages/{Overview, Trends, Topics, Entities}.tsx
    ├── articles/  api.ts · ArticleList · pages/Articles.tsx (list + detail)
    └── system/    StatusPill · DemoBanner · AnalysisBanner · pages/{About, Status, NotFound}.tsx
```

Tests stay next to their files (`*.test.tsx`), as they are now.

### Enforcement, with no new dependency

A `@/*` → `src/*` path alias (tsconfig `paths` + Vite `resolve.alias`) makes every cross-layer import name its layer, so ESLint's built-in `no-restricted-imports` can enforce the arrows using the flat config the repo already has:

```js
// eslint.config.js (sketch). Relative imports stay inside a folder; "../../*" is banned everywhere.
const LEAVE_FOLDER = { group: ["../../*"], message: "Cross a layer through the @/ alias." };
{ files: ["src/ui/**"], rules: { "no-restricted-imports": ["error", { patterns: [LEAVE_FOLDER,
  { group: ["@tanstack/*", "react-router*", "zustand*"], message: "ui/ is pure: pass data and callbacks in." },
  { group: ["@/features/*", "@/stores/*", "@/app/*", "@/shared/api/*"], message: "ui/ may import shared/lib, shared/model, design only." },
]}]}},
{ files: ["src/shared/**"], rules: { "no-restricted-imports": ["error", { patterns: [LEAVE_FOLDER,
  { group: ["react", "@tanstack/*", "react-router*", "zustand*", "@/ui/*", "@/features/*", "@/stores/*", "@/app/*"] },
]}]}},
{ files: ["src/features/**"], rules: { "no-restricted-imports": ["error", { patterns: [LEAVE_FOLDER,
  { group: ["@/features/*/*"], message: "Import another feature through its index (@/features/<name>)." },
]}]}},
```

Flat config replaces a rule's options per matching block rather than merging them, so each folder's block repeats the shared pattern. If this proves too loose, `eslint-plugin-boundaries` is the heavier fallback.

`shared/lib/useTitle.ts` is a React hook. It moves to `app/` or `features/system/`, or the `shared/` rule gets a narrow exception. This is decided during the move.

### Component contracts

- **ui components** take data and callbacks as props, render semantic HTML, and style only through tokens. Every visual state (loading, empty, error, disabled, pressed) is a prop, never a fetch. Each gets a Vitest render test. Dark mode needs no test of its own, because it comes from tokens.
- **Feature blocks** own exactly one concern: they call one or more query hooks, read URL or store state, and pass plain props down. Pages are thin compositions of blocks.
- **Styling:** move from one global `app.css` to **CSS Modules colocated with `ui/` and `features/` components** (built into Vite; CSS splits per lazy chunk automatically). Globals are limited to `design/`. This is about ownership and dead-code safety, not speed: today's CSS is only 4.1 KB gz. Inline `style={{}}` is allowed only for data-driven custom properties (`--col-color`, `--dot-bias`). The other ~70 move into classes.

---

## 2. State and data-flow topology

### Four homes for state

| Home | Holds | Library | Persistence | Examples |
|---|---|---|---|---|
| **Server cache** | anything the API returns | TanStack Query | memory (`gcTime`), plus HTTP cache | stories, story detail, sources, analytics, status |
| **URL** | what defines *what is shown* and must survive share, reload and back | React Router search params | the link itself | `days`, `source`, `sort`, `topic`, `country`, `q`, `page`, `kind`, **`lens` (new, overrides the preference)** |
| **Client-global** | user preferences and history that outlive a page and are not shareable | **Zustand** + `persist` | `localStorage` (only in this browser, ADR-022) | theme, default lens, reading history |
| **Local** | ephemeral, single-component interaction state | `useState` / `useReducer` | none | search draft before debounce, Card chart/table toggle |

**Where does a new piece of state go?** Ask in order. Did it come from the API? Then the server cache. Should a shared link reproduce it? Then the URL. Must it survive navigation or reload, or be read by unrelated components? Then the Zustand store. Otherwise it is local, kept in the lowest component that needs it.

**Hard rules**
1. Server data is never copied into Zustand or `useState`. Derive with `select` or `useMemo` from the query result.
2. Nothing representable in the URL goes into a store. The store holds *defaults*; the URL holds the *current* view (for example, `lens` param ?? stored lens ?? computed default).
3. Stores never fetch. Query functions never read stores. Anything a query depends on goes in its key, as a parameter.

### Is Zustand worth adding?

At today's size it is a **consistency** win, not a performance win. It replaces three hand-written persistence patterns (≈80 lines) with one, fixes the per-instance lens state (F9), and gives selector subscriptions. Cost: a small runtime dependency (low single-digit KB gz with `persist`; measure on adoption). If it is declined, the fallback is one `createPersistedStore()` helper on `useSyncExternalStore`, the pattern `reading.ts` already uses. That is decision **D2** in §6.

```ts
// stores/preferences.ts (sketch)
type Theme = "light" | "dark" | "system";
interface Preferences { theme: Theme; lens: Lens | null; setTheme(t: Theme): void; setLens(l: Lens): void }
export const usePreferences = create<Preferences>()(persist(
  // initial values read today's keys (gjurme-theme, gjurme-lens) once, so no reader loses a setting
  (set) => ({ theme: legacyTheme(), lens: legacyLens(), setTheme: (theme) => set({ theme }), setLens: (lens) => set({ lens }) }),
  { name: "gjurme-prefs", version: 1, storage: createJSONStorage(() => safeLocalStorage) },
));
// subscribe to one primitive, never the whole store:
const lens = usePreferences((s) => s.lens);
```

Two requirements carry over from the current code:
- **Storage may throw** (private mode, blocked storage), so `safeLocalStorage` wraps every call in `try/catch`. Without storage the app still works for the page view.
- **Cross-tab sync.** Reading history updates other tabs today. `persist` does not do that by itself, so a `storage` event listener calls `usePreferences.persist.rehydrate()` (and the same for `reading`).

`public/theme.js` stays. It applies the theme before first paint, which no store can do. It is updated to read the new key.

### Data flow

```mermaid
sequenceDiagram
    autonumber
    participant U as URL
    participant R as Router (data router)
    participant L as Route loader
    participant Q as Query cache
    participant API as /api/v1
    participant P as Page + blocks
    U->>R: navigation (/stories/12?lens=region)
    par code and data start together
        R->>R: import() route chunk
        R->>L: loader({ params, request })
        L->>Q: queryClient.prefetchQuery(storyQuery(12))
        Q->>API: GET /stories/12 (if missing or stale)
    end
    R->>P: render (chunk ready)
    P->>Q: useQuery(storyQuery(12)) (in flight or cached)
    P->>P: lens = URL ?? preferences store ?? default
    API-->>Q: JSON
    Q-->>P: data, then blocks receive plain props
```

- **Query options factories**, one per feature (`features/stories/api.ts`), are the single definition of each key, fetcher and freshness. Hooks, loaders and hover prefetch all use them:
  ```ts
  export const storyQuery = (id: number) => queryOptions({
    queryKey: ["stories", "detail", id] as const,
    queryFn: ({ signal }) => apiGet<StoryDetail>(`/api/v1/stories/${id}`, undefined, signal),
    staleTime: FRESH.feed,
  });
  ```
  Keys become hierarchical (`["stories", "feed", params]`, `["stories", "detail", id]`) instead of `[path, params]`, so related data can be invalidated as a group.
- **Loaders prefetch; they do not block.** A loader calls `prefetchQuery` and returns `null`, so navigation is never held behind the network, and the page keeps its loading, error and empty Card states (F4).
- **Hover and focus prefetch** on story links: `queryClient.prefetchQuery(storyQuery(id))` plus the route's `lazy()`. One line in `StoryCard`.

**Freshness by resource class.** The pipeline refreshes every 15 minutes, and the API sends `Cache-Control: public, max-age=60, stale-while-revalidate=120`:

| Class | Examples | `staleTime` | Other |
|---|---|---|---|
| `feed` | stories, story, blindspots, articles | 60 s | `refetchOnWindowFocus: true`, so a returning reader sees new stories (today it is off globally) |
| `analytics` | overview, volume, trends, entities, sources | 5 min | changes only when the pipeline runs |
| `static` | topic taxonomy | `Infinity` | changes only with a deploy |
| `status` | `/status` | 60 s | `refetchInterval: 5 min` while visible, so the "Updated …" pill stays honest |

### Re-render rules (and where they apply today)

1. **Colocate ephemeral state.** The search draft moves into `features/stories/SearchField`, which keeps its own text and writes `q` to the URL after a 350 ms debounce. Keystrokes then re-render one input, not the feed (F7, same on Articles and Entities).
2. **Subscribe narrowly.** Zustand selectors return primitives. Query consumers that need one field use `select` (for example, the status pill needs `status` and `last_success_at`), and structural sharing then suppresses re-renders when other fields change.
3. **Keep router hooks out of leaves.** `ArticleList` gets prebuilt `href`s, and the focus/scroll effect moves to a `RouteFocus` sibling so the shell no longer subscribes to `useLocation` (F8).
4. **Memoise only what was measured.** Lists are ≤ 20 items (feed 15, articles 20), so virtualisation and blanket `memo` are not needed. Profile with the React DevTools profiler first. React Compiler is worth evaluating once its Vite 8 integration is confirmed, as a separate change.

---

## 3. Performance and scalability strategy

### Budgets (enforced in CI)

| Budget | Today | Target |
|---|---:|---:|
| Entry closure JS (gz) | 95.2 KB | ≤ 96 KB, and fails CI above |
| Home route total JS + CSS (gz) | ≈108 KB | ≤ 110 KB |
| Any non-chart route increment (gz) | 5–9 KB | ≤ 15 KB |
| Chart route increment (gz) | 109–112 KB | ≤ 115 KB (Recharts is the floor; see below) |
| Fonts on first paint | 0 (system) | ≤ 1 preloaded file, ≤ 110 KB for all faces combined |
| LCP, home, mobile, Fast 4G (Playwright trace) | not measured | ≤ 2.5 s |
| CLS | not measured | ≤ 0.05 (font metric overrides, fixed skeleton heights) |

Implementation: set `build.manifest: true`, and a ~40-line Node script (`frontend/scripts/budget.mjs`) walks the manifest from each route entry, gzips the files and compares the totals with `budgets.json`. It runs in the existing Frontend CI job. No new dependency.

### Code splitting

1. **Keep route-level `lazy`**, moved into router objects (`lazy: () => import(...)`) so React Router can load code and run the loader in parallel (F4).
2. **Make the vendor rule exact.** `/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler)\//` moves `react-redux` and `use-sync-external-store` into the Recharts chunk (−1.1 KB gz measured).
3. **Prefetch the likely next chunk.** After the feed renders, on `requestIdleCallback` (falling back to `setTimeout`), prefetch the Story route chunk; hover and focus prefetch covers the rest.
4. **Recharts stays for now.** It costs nothing on the home and story routes. Replacing it with hand-rolled SVG (as `CoverageBar` already does) would save ≈90 KB on five secondary routes but rewrite 8 chart components. Revisit only if the dashboard becomes a primary entry route.
5. **Do not split further.** Chunks under 2 KB (`StatTile`, `filters`, `FilterBar`) cost more in requests than they save. Leave them, and revisit only if request count shows up in the LCP trace.

### Delivery and caching layers

| Layer | Today | Target |
|---|---|---|
| **Browser HTTP: hashed `/assets/*`** | `immutable, 1y` | unchanged, but **a missing asset returns 404, not `index.html`** (F2) |
| **Browser HTTP: HTML, deep links, unhashed files** | only `/` and `/index.html` get `no-cache` | `no-cache` (ETag revalidation) on **everything outside `/assets/`** (F3) |
| **Browser HTTP: API** | `public, max-age=60, swr=120` (backend) | unchanged; it matches the `feed` `staleTime` |
| **Edge (Caddy)** | compression, no cache | unchanged. One VPS and a 60 s API cache need no edge cache; revisit behind a CDN. |
| **In-app: TanStack Query** | 60 s for everything | per-class freshness (§2) |
| **Service worker** | none | **none**. Offline news is stale news, and a broken SW is hard to recover. Revisit only for a real install or offline requirement. |

```caddy
handle {
    root * /srv
    @assets path /assets/*
    handle @assets {                       # sibling handles are mutually exclusive
        header Cache-Control "public, max-age=31536000, immutable"
        file_server                        # no SPA fallback: a missing chunk is a real 404 (F2)
    }
    handle {
        header Cache-Control "no-cache"    # HTML, deep links, theme.js, manifest, icons (F3)
        try_files {path} /index.html
        file_server
    }
}
```

The `try_files` must sit inside the non-asset `handle`. At the outer level, Caddy runs `try_files` before `handle`, so `/assets/missing.js` would be rewritten to `/index.html` before the `@assets` matcher ever saw it.

### Deploy-skew resilience (F1)

- `app/RouteError.tsx` is the router's `errorElement`. If the error is a chunk-load failure (`TypeError: Failed to fetch dynamically imported module`, or Vite's `vite:preloadError` event), it reloads **once**, guarded by a `sessionStorage` timestamp so it cannot loop. Otherwise it shows the existing `ErrorState` with "Try again" and keeps the shell and navigation usable.
- With F2 and F3 fixed, a reload always gets fresh HTML and current chunks.

### Fonts (see §4)

Self-hosted woff2 is required anyway: the CSP has `font-src 'self'`, and the privacy promise means no third-party requests.
- Subsets: `latin` + `latin-ext`. Albanian needs ë and ç, and names in the news need č ć š ž đ (Dačić, Vučić).
- `font-display: swap`. Preload **only** the UI text face. Headline and mono faces load on use.
- Size-matched fallbacks (`size-adjust`, `ascent-override`, `descent-override`) on a local fallback face keep the swap within the CLS budget.

### Link previews (F11): a backend item, listed for completeness

Shared story links need per-story `<title>` and `og:*` tags. The cheapest fix fits the existing architecture: FastAPI answers `GET /stories/{id}` for **bot user agents only**, with `index.html` plus injected meta (headline, outlet count; never article text, per ADR-003). Readers keep the static SPA. Separate change, separate review.

---

## 4. Anti-convergence design system

### The stance

GJURMË is a product *about* how outlets differ. The design follows from that:

1. **Colour belongs to data.** Every hue on screen encodes something: perspective, region, ownership, factuality or status. The chrome (text, links, navigation, focus, borders) is **ink on paper**. This fixes F5 for good: a link can never look "left".
2. **Identity comes from typography and the trace,** not from a brand gradient. Headlines in a news serif, in the outlets' own language. The *gjurmë* (trace) motif appears as thin rules and the story timeline.
3. **Editorial, not dashboard-SaaS.** Hairline rules and spacing separate content instead of rounded, shadowed cards. Dense where data is dense; a generous reading measure where text is long.

### Token tiers

| Tier | Purpose | Example | Who may use it |
|---|---|---|---|
| 1. Primitive | raw validated steps | `--blue-600: #2a78d6` | tier 2 and 3 tokens only |
| 2. Chrome role | UI meaning | `--paper`, `--ink`, `--link`, `--rule`, `--focus` | all components |
| 3. Data role | encoding meaning | `--bias-left`, `--cat-3`, `--fact-high`, `--unrated` | data marks only (bars, dots, chart series) |

CI guard (a `grep` in the Frontend job): no hex, `rgb()` or `hsl()` outside `design/tokens/` (it holds today, with 0 occurrences), and no tier-3 token in a non-data selector.

### Colour

**Chrome.** All text pairs checked for WCAG contrast (computed, not estimated):

| Token | Light | Dark | Contrast (light/dark) |
|---|---|---|---|
| `--paper` (page) | `#f4f2ec` newsprint | `#121211` | — |
| `--surface` (cards, **all data marks sit here**) | `#fcfcfb` (unchanged) | `#1a1a19` (unchanged) | — |
| `--ink` | `#0b0b0b` | `#f2f0ea` warm white (was `#fff`) | 17.6 / 16.5 on paper |
| `--ink-2` | `#52514e` | `#c3c2b7` | 7.1 / 10.5 on paper |
| `--ink-muted` | `#686660` | `#9a9890` | 5.1 / 6.5 on paper |
| `--link` | `= --ink`, underlined; 2px underline on hover | `= --ink` | as ink |
| `--focus` | `= --ink`, 2px ring, 2px offset | `= --ink` | ≥ 15:1 |
| `--rule` | `rgba(11,11,11,.12)` hairline | `rgba(255,255,255,.12)` | non-text |
| `--rule-strong` | `#c3c2b7` (column rules, active-nav underline) | `#383835` | non-text |

The data marks keep their **validated surface**. Only the page background warms up. Run against the warmer `#f6f3ec` as a chart surface, the validator dropped a fourth categorical slot (`--cat-2`) below 3:1. So data never sits directly on `--paper`.

**Data.** The validated tokens in today's `tokens.css` are unchanged (categorical slots 1–6 in fixed order, ordinal factuality ramp, diverging perspective, hatched unrated). Validator, 2026-10-11:
- Light categorical: all checks pass. Contrast warns for 3 slots, and the coverage bars already carry the required relief (printed percentages, 2px gaps).
- Dark categorical: all checks pass, including contrast.

**Open question, decision D5: perspective colours.** The tokens use the US convention Ground News uses (blue = left, red = right). European readers, Albanian-language readers included, more often read **red as the left**. Options: (a) keep US blue/red, matching Ground News, which some readers will know; (b) swap to red-left/blue-right; (c) use a **non-partisan diverging pair** that no party owns (for example teal ↔ amber). Option (c) is the most honest for a bias tool and avoids both conventions, but it must be re-validated and must not collide with the categorical slots used for region. Recommendation: **(c)**, validated with the palette script before adoption.

### Type

| Role | Face | Why this one |
|---|---|---|
| **Headlines** (story titles, page titles; mostly Albanian text) | **Newsreader** (Production Type, OFL), static 600 + 600 italic, `opsz` set for display | Drawn for news reading on screens. Gives story headlines the authority of a front page and separates "the news" (serif) from "the tool" (sans). Not one of the overused AI-default serifs. |
| **UI and body** | **Atkinson Hyperlegible Next** (Braille Institute, OFL), variable `wght` 400–700 | Designed for character disambiguation (l/I/1, O/0). That fits a site of names, numbers and percentages, and it signals the accessibility commitment the site already makes. Distinctive without being decorative. |
| **Figures** (stat tiles, tables, percentages) | **Atkinson Hyperlegible Mono**, 500 | Same skeleton as the body face, fixed-width figures. Numbers align in tables without a third family's voice. |

To verify before adoption (D4): glyph coverage for ë ç č ć š ž đ in all three, `tnum` support (or use the mono for figures), and woff2 size after subsetting against the 110 KB budget.

Fallback stack: `"Atkinson Hyperlegible Next", <metric-matched local fallback>, system-ui, sans-serif` and `"Newsreader", <metric-matched Georgia>, Georgia, serif`.

**Scale.** It replaces the 22 ad-hoc sizes. Steps are spaced so neighbouring roles are clearly distinct.

| Token | Size | Line height | Use |
|---|---|---|---|
| `--text-xs` | 0.75rem (12) | 1.35 | meta, legends, badges |
| `--text-sm` | 0.8125rem (13) | 1.4 | secondary UI, table cells |
| `--text-base` | 0.9375rem (15) | 1.55 | body, controls |
| `--text-md` | 1.0625rem (17) | 1.35 | card titles, story-card headline (serif) |
| `--text-lg` | 1.25rem (20) | 1.25 | section titles, lead-story headline (serif) |
| `--text-xl` | 1.5rem (24) | 1.2 | page titles |
| `--text-display` | `clamp(1.75rem, 1.2rem + 1.8vw, 2.375rem)` | 1.1 | story page headline (serif) |

Weights: sans 400 and 600 only; serif 600 only (8 weights become 3). Measure: body text ≤ 70ch, headlines ≤ 32ch. Tabular figures wherever numbers stack.

### Space, shape, depth

- Spacing: `--space-1…7` = 4 · 8 · 12 · 16 · 24 · 32 · 48 px. The 61 distinct declarations snap to these.
- Radius: `--radius-sm 2px`, `--radius 4px` (from 6/10). Circles stay only where the shape means something (source dots, status dot).
- Depth: no shadows on content. Cards are separated by `--rule` hairlines and `--space-5`. Shadow is kept only for things that float (popovers, the sticky header once scrolled).

### Motion orchestration

Tokens: `--dur-instant 80ms` · `--dur-quick 140ms` · `--dur-base 200ms` · `--dur-slow 320ms`; `--ease-out cubic-bezier(.2,.7,.2,1)` · `--ease-in-out cubic-bezier(.45,0,.2,1)`.

Rules:
1. **Motion explains a change in data or state, never decorates.** Allowed: refetch dim (opacity, `--dur-quick`), a new value crossfading in, a coverage bar re-proportioning *within* a lens on data refresh (`flex-grow`, `--dur-base`), disclosure open/close, the chart/table toggle.
2. **Nothing animates on page load.** No staggered card fade-ins, no count-up numbers, no skeleton shimmer longer than the actual wait (prefer a static skeleton; shimmer only after 400 ms).
3. **One thing moves at a time.** Exit is faster than enter (`--dur-instant` vs `--dur-quick`). Route changes cut; they don't slide.
4. **Only `opacity` and `transform`,** plus the coverage-bar `flex-grow` exception (≤ 4 segments × ≤ 15 cards).
5. **Reduced motion:** the existing global guard stays, and charts keep `isAnimationActive={!still}`.

### Signature element: the trace

The story page timeline becomes a **horizontal trace**: one hairline across the column, one tick per outlet report at its publish time, coloured by the current lens, with the first report marked and labelled. It is the product's name drawn as data ("who left a mark on this story, and when"), and the one place the design takes a visual risk. Story cards carry a 3px version of the coverage bar as their top rule, so the feed reads as a column of traces.

### Never

- a brand gradient, glassmorphism, or a purple-to-blue hero;
- a hue in the chrome that also encodes data (F5);
- Inter, Roboto, or the bare system stack as the brand face;
- rounded-xl cards with soft drop shadows as the default container;
- emoji as icons (the theme toggle's ☾ ☀ ◐ glyphs become drawn SVG icons);
- a chart without a table view, or colour as the only carrier of meaning (existing rule, kept).

---

## 5. Migration plan

Each phase is one PR, ships independently, and keeps every existing test green. P0 fixes come first because they do not depend on any decision below.

| Phase | Content | Depends on | Risk |
|---|---|---|---|
| **0. Resilience** | Caddy cache and 404 fix (F2, F3), `RouteError` with chunk-reload (F1), exact vendor chunk rule | — | low |
| **1. Tokens** | split `tokens.css`; add type, space and motion scales; snap the 22 sizes and 61 spacings; remove ~70 inline styles. Visual change is limited to snapping. | — | low (axe and e2e screenshots) |
| **2. Structure** | folder moves (`git mv`), ESLint boundaries, CSS Modules for moved components | D1 | medium (mechanical, large diff) |
| **3. State** | Zustand stores with legacy-key migration, `lens` URL param, `SearchField` colocation, `RouteFocus` | D2, D3 | low |
| **4. Data router** | `createBrowserRouter`, loaders with `prefetchQuery`, query option factories, freshness classes, hover prefetch | phase 2 | medium |
| **5. Identity** | fonts, ink chrome, radius/rules, trace timeline, perspective palette | D4, D5, D6 | medium (visual review) |
| **6. Guards** | bundle budgets in CI, generated OpenAPI types with a CI diff check | phase 4 | low |

---

## 6. Root blocks to review before implementation

| # | Decision | Recommendation |
|---|---|---|
| **D1** | Layering `app → features → ui/shared/stores → design`, with feature folders and lint-enforced boundaries (§1) | **Adopt** |
| **D2** | Zustand for client-global state, versus one in-house `useSyncExternalStore` helper (§2) | **Zustand**, for one pattern and selector subscriptions; the cost is small and measured on adoption |
| **D3** | `lens` in the URL (shared links reproduce the view), with the stored lens as the default | **Adopt** |
| **D4** | Type pairing: Newsreader (headlines) + Atkinson Hyperlegible Next (UI/body) + Atkinson Hyperlegible Mono (figures) | **Adopt**, pending the glyph, `tnum` and size checks |
| **D5** | Perspective colours: US blue-left/red-right, European red-left, or a non-partisan pair | **Non-partisan pair**, validated before use |
| **D6** | Ink-on-paper chrome (no brand hue; links and focus in ink), with data marks staying on the validated surface | **Adopt** |
| **D7** | Per-story link previews through a bot-only FastAPI route (§3) | **Defer** to its own backend PR |

Once D1–D6 are settled, implementation starts at phase 0, which needs none of them.
