# AI enrichment

Each article's **headline and short feed excerpt** (never the full article) is sent to Claude once. The model returns a structured analysis: language, topics, tone, event type, an English one-sentence summary, named entities and countries. That analysis is validated, checked against the source text, stored with full lineage, and becomes the input for every chart.

Code: `backend/src/gjurme/enrichment/`: `prompt.py`, `schema.py`, `providers.py`, `grounding.py`, `budget.py`, `pricing.py`, `service.py`.

## What is extracted

| Field | Type / vocabulary | Used for |
|---|---|---|
| `language` | ISO 639-1 (`sq`, `en`, `sr`, `mk`, …) | Filtering, data-quality |
| `primary_topic` | one of 19 slugs (`taxonomy.py`) | Topic rankings, momentum, source profiles |
| `secondary_topics` | 0–3 slugs, primary excluded | Topic detail pages |
| `sentiment` | `negative` \| `neutral` \| `positive` | Tone mix |
| `sentiment_score` | −1.0 … 1.0, consistent with the label | Average tone, tone shift |
| `event_type` | controlled list (`EVENT_TYPES`) | Article metadata |
| `summary_en` | one neutral English sentence, ≤ 35 words | Article lists (our own text, not the publisher's) |
| `entities` | ≤ 12 × `{name, type: person\|organization\|location}` | Entity rankings, spikes, co-occurrence |
| `countries` | ≤ 6 ISO 3166-1 alpha-2 codes (Kosovo = `XK`) | Article metadata |
| `confidence` | 0.0 … 1.0, self-reported | Low-confidence data-quality check |

The taxonomy is a closed vocabulary on purpose: trends need stable categories, and free-text topics would fragment ("Zgjedhjet", "elections", "votimi"). Changing it means bumping `PROMPT_VERSION` and re-enriching (see [Versioning](#versioning-and-reprocessing)).

## Request

```python
client.messages.create(
    model="claude-sonnet-5",                          # LLM_MODEL
    max_tokens=1500,                                  # LLM_MAX_OUTPUT_TOKENS
    system=[{"type": "text", "text": SYSTEM_PROMPT,   # ~5.4k chars ≈ 1.3k tokens, identical
             "cache_control": {"type": "ephemeral"}}],  # for every call → prompt-cached
    messages=[{"role": "user", "content": render_user_message(article)}],
    output_config={"format": {"type": "json_schema", "schema": OUTPUT_JSON_SCHEMA}},
    thinking={"type": "disabled"},                    # extraction, not reasoning
)
```

- **Structured outputs** (`output_config.format` with a JSON schema) make the model emit JSON that matches the schema: enums for topics, sentiment, event and entity types, required fields, `additionalProperties: false`.
- **Thinking.** It is disabled for Sonnet 5 / Opus 5 / 4.x. Models that cannot disable it (Opus 5.5, the Fable tier) get `effort: "low"`. Haiku 4.5 gets neither (`_thinking_kwargs`).
- **The client is explicit.** `base_url` is always set from `ANTHROPIC_BASE_URL` (default `https://api.anthropic.com`), so an ambient environment variable can never silently redirect production traffic. The SDK timeout (60 s) and SDK retries (2, with backoff, for 408/409/429/5xx and connection errors) are configurable.
- **The user message** is the article wrapped in tags, with `<`, `>` and `&` escaped so article text cannot close the wrapper:

```xml
<article>
<source>Kallxo</source>
<published>2026-09-24</published>
<headline>Kuvendi miratoi buxhetin &lt;b&gt;për&lt;/b&gt; 2027</headline>
<excerpt>Deputetët e Kuvendit të Kosovës votuan sot...</excerpt>
</article>
```

### The system prompt (summary)

The full text is `SYSTEM_PROMPT` in `prompt.py`. Its sections:

1. **Role and priority.** "Precision matters more than coverage: a missing entity is acceptable, an invented one is not."
2. **Security.** The article is untrusted data, and instructions inside `<article>` are analysed, never followed (prompt-injection guard; the entity-grounding step below is the second line of defence).
3. **Topics.** Every slug with a one-line definition, plus disambiguation rules for the Balkan context: a court case about a politician is `crime_justice` + `politics`; the Belgrade–Pristina dialogue and north Kosovo are `kosovo_serbia`; visa liberalisation is `eu_integration`.
4. **Event type.**
5. **Sentiment.** The tone of the *reported situation* for the public, not the author's style. Score bands are tied to the label (negative < −0.15 < neutral < 0.15 < positive), and |score| > 0.7 is reserved for extreme events.
6. **Entities.** Only entities *explicitly* mentioned, in the fullest form that appears in the text. Never add first names, titles or roles from world knowledge. Albanian names are returned in the nominative, with type rules and examples.
7. **Summary, countries, confidence.**

## Validation pipeline

```
API response
  └─ stop_reason == "refusal"      → status=refused   (not retried)
  └─ stop_reason == "max_tokens"   → status=invalid   (truncated JSON)
  └─ JSON parse (tolerates ```json fences from providers without structured output)
  └─ _repair(): soft fixes, each recorded in quality_flags
        · duplicate / primary-repeating secondary topics removed
        · duplicate entities merged, > 12 truncated, 1-char names dropped
        · country codes upper-cased, invalid ones dropped
        · summary > 400 chars truncated
        · scores clamped to their ranges
        · score contradicting the label (e.g. "negative" with +0.4, or "neutral" with |score| > 0.5)
          → replaced by the label's default score (the categorical judgement is trusted)
  └─ Pydantic EnrichmentOutput (extra="forbid", enums, lengths) → status=invalid on failure
  └─ ground_entities(): drop entities not supported by the headline/excerpt
        · persons: every name token (≥ 3 chars) must appear
        · organizations / locations: at least half of the tokens
        · matching is diacritic-insensitive with a 5-character shared prefix, because Albanian
          inflects names ("Prishtinës" in the text, "Prishtina" in the output)
        · short acronyms (EU, BE, OK) need an exact token match
  └─ persist: enrichments row (is_current) + denormalized fields on articles + bridges
```

Every rejected or repaired item stays visible: `core.enrichments.status`, `error`, `raw_response` (for failures, kept 90 days) and `quality_flags` (e.g. `{"entities_ungrounded": [...], "sentiment_inconsistent": true}`). The `ungrounded_entity_rate_24h` and `low_confidence_rate_24h` data-quality checks track the trend.

## Reliability

| Situation | Handling |
|---|---|
| Timeout, connection error, 429, 5xx | SDK retries with backoff; if still failing, the attempt is stored as `failed` and the article is retried in later runs, up to `ENRICH_MAX_ATTEMPTS` (3). |
| Authentication / permission error, unknown model | **Fatal**: the stage stops for this run, the article's attempt counter is *not* consumed, and a critical alert fires. Fixing the key or model resumes work where it stopped. |
| 5 consecutive failures | Circuit breaker opens; the stage stops; critical alert. |
| Refusal | Stored as `refused`, not retried (the same input would be refused again). |
| Invalid output | One repair pass (above), otherwise `invalid` with the raw response. |
| Process crash mid-stage | Nothing is lost: the article is still `pending` or `failed`. |

Concurrency is `ENRICH_CONCURRENCY` (4) worker threads. Budget reservations are thread-safe, and all database writes happen on the main thread.

## Cost controls

1. **Daily budget (hard cap).** Before each call, a pessimistic cost estimate is reserved against `LLM_DAILY_BUDGET_USD`. The estimate assumes a cache *write*, ~3 characters per token and the full `max_tokens`: ≈ $0.019 for Sonnet 5 against ≈ $0.004 actual. After the call the reservation is replaced by the actual cost from the API's usage report. When the budget is reached, no further calls are dispatched; the rest stays `pending`, newest first, for the next day. Today's spend is computed from `core.enrichments`, so restarts cannot reset it.
2. **Per-run cap.** `ENRICH_MAX_PER_RUN` (150) bounds the cost and duration of one run.
3. **Kill switch.** `POST /api/v1/admin/enrichment/pause` writes `ops.settings`, and every enrichment stage checks it before its first call, with no redeploy. It takes effect from the next run (≤ 15 minutes); a batch already in flight finishes, bounded by the per-run cap and the budget. `ENRICHMENT_ENABLED=false` does the same through configuration.
4. **Never pay twice.** Dedup L1–L4 stops duplicates before enrichment. The **enrichment cache** reuses a previous result when `input_hash` (prompt version, schema version, model, title, excerpt) matches another article's successful enrichment, stored as `status=cached` at $0. An article's *own* previous result is never reused, so re-enrichment really re-asks.
5. **Prompt caching.** The ~1.3k-token system prompt is identical for every call and marked `cache_control: ephemeral`, so after the first call it is read from cache at 0.1× the input price. `cache_read_tokens` / `cache_write_tokens` are stored per call, which shows whether caching is effective in production. If a model's minimum cacheable length were above the prompt size, calls still work, just without the discount.
6. **Unknown models are priced at the most expensive rate** in the pricing table, so a typo or new model can never make the budget guard under-count.

### Cost model

Estimated from token counts, **not measured**: no API key was available while this was built. `GET /api/v1/admin/costs` reports the real numbers once enrichment runs.

Assumptions per article: ~350 input tokens (template + headline + excerpt), ~300 output tokens (the JSON), ~1.4k cached system-prompt tokens read at 0.1×. Prices are from `enrichment/pricing.py`, which reflects Anthropic's published per-MTok prices at build time. Re-check them before relying on the figures.

| Model | $/MTok in / out | $/article | 100/day | 500/day | 1,000/day | 10,000/day |
|---|---|---|---|---|---|---|
| `claude-haiku-4-5` | 1 / 5 | 0.0020 | $0.20 | $0.99 | $1.99 | $19.90 |
| **`claude-sonnet-5`** (default) | 2 / 10 | 0.0040 | $0.40 | $1.99 | $3.98 | $39.80 |
| `claude-opus-5-5` | 4 / 20 | 0.0080 | $0.80 | $3.98 | $7.96 | $79.60 |
| `claude-opus-5` | 5 / 25 | 0.0100 | $1.00 | $4.98 | $9.95 | $99.50 |

Per month (×30) at the default model: 100/day ≈ $12, 500/day ≈ $60, 1,000/day ≈ $119, 10,000/day ≈ $1,194. The default `LLM_DAILY_BUDGET_USD=2.00` caps spend at ≈ $60/month, whatever the volume. The five verified sources currently publish on the order of hundreds of items per day, so the default budget covers them with headroom (to be confirmed by `/admin/costs` after launch).

Levers, cheapest first: keep dedup and caching on (default), use the Message Batches API for non-urgent backfills (−50%; a V2 item), move to `claude-haiku-4-5` if the evaluation below shows acceptable quality, or lower `ENRICH_MAX_PER_RUN` / the budget.

## Model choice

`claude-sonnet-5` is the default ([ADR-010](DECISIONS.md#adr-010-default-model-claude-sonnet-5-thinking-disabled)). The task is multilingual extraction and classification from ~100 words of Albanian. That needs good Albanian reading, careful entity handling (inflection, no invented first names) and calibrated tone. It needs no multi-step reasoning, so thinking is disabled and the most capable tier is not worth 2–2.5× the price. Haiku 4.5 is half the price and a reasonable choice if a quality check on real articles confirms it. That check needs a key, so it is on the launch checklist.

Switching models is configuration only (`LLM_MODEL`). The model is part of `input_hash`, so cached results are never reused across models.

## Versioning and reprocessing

- `PROMPT_VERSION = "v1.0"` (prompt.py) and `SCHEMA_VERSION = "2026-09-24.1"` (schema.py) are stored on every enrichment row, next to model, tokens, cost, latency, attempt number and the provider's request id.
- Bump `PROMPT_VERSION` whenever the prompt text, the taxonomy or the schema changes.
- Reprocess:
  ```bash
  gjurme enrich-requeue --older-than-version v1.0   # mark older analyses for re-enrichment
  gjurme enrich --limit 500                          # or let the scheduler work through it
  gjurme enrich-requeue --failed                     # retry failed/skipped articles
  gjurme enrich-requeue --article-id 123             # one article (also: POST /admin/articles/123/reenrich)
  ```
  History is kept. The new row becomes `is_current` and the old one stays for comparison. The daily budget applies to reprocessing too.

## Free mode: keyword rules

Without an API key the pipeline can run the keyword-rule provider in production (`LLM_PROVIDER=fake` with `ALLOW_FAKE_LLM_IN_PRODUCTION=true`; "fake" is the internal name). It assigns:
- the topic, from lists of Albanian keyword stems;
- the tone, from positive and negative word lists;
- names, from capitalised word sequences, with role words stripped;
- a fixed confidence of 0.3;
- no summary: the field holds `[headline, no AI summary] …`.

It costs nothing and is **much less accurate**, so it is always disclosed:
- `GET /api/v1/status` → `analysis: {mode: "ai" | "rules" | "mixed" | "none", rule_based_share, model}`, computed over the last 30 days;
- a banner on every page when the mode is `rules` or `mixed` (except on demo data, which has its own banner);
- each article page says *Rule-based analysis* or *AI analysis (model)*, from the provider of its current enrichment;
- the methodology page states the current mode.

**Switching to Claude later:** set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`, remove the flag, restart the scheduler, then `gjurme enrich-requeue --provider fake`. The rule-based results are re-analysed within the daily budget, newest first.

## Testing without a key

- **FakeProvider** (`LLM_PROVIDER=fake`): deterministic keyword heuristics for development, the demo and tests. It is refused in staging and production unless explicitly allowed.
- **Wire-level test** (`tests/integration/test_anthropic_wire.py`): runs the *real* `AnthropicProvider` and SDK against a local HTTP server that implements the Messages API contract. It checks the request body (model, cached system block, `output_config`, thinking), the parsing of usage, cost and request id, refusal and `max_tokens` handling, 401/403/404 → fatal, and 429/529 → retried by the SDK, then a retryable failure.
- **Live check and quality review** (`.github/workflows/sources.yml`, job `live-pipeline`): runs ingest, process and enrich against the real feeds on GitHub's runners. When the repository secret `ANTHROPIC_API_KEY` exists, Claude analyses the newest articles, 8 by default or 1–50 via *Run workflow → enrich_limit*, under a hard budget of $0.02 per article (at most $1). The job then publishes a **review report** in the run summary and as the `live-pipeline-stats` artifact: every result next to its headline (topic, tone, names, names dropped by grounding, summary, confidence), plus totals for calls, tokens, cache hits, cost per article and latency. Without the secret it uses the keyword rules.
