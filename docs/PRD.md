# Dispensary Price-Comparison Engine — Product Requirements (PRD)

Status: Living document. Version 1.0.
Owner: Mat Riexinger. Engine implementation: `pek_engine/`.

---

## 1. Problem & Vision

Retail cannabis has **no universal product catalog**. The same physical product —
say a *Stiiizy 1g Blue Dream Pod* — is listed differently at every dispensary,
on different POS/menu platforms (Dutchie, Carrot, Jane, Blaze, Weedmaps, AIQ,
Proteus420, …), with inconsistent titles, brands, categories, sizes, and
potency formats. There is no shared ID across stores (we verified: `product_id`
is per-store unique — 0 of 19,644 listings shared an ID across dispensaries).

**Vision:** a product finder + price-comparison search engine. Every dispensary's
messy menu item is normalized into **one canonical product** so a shopper can
search a product once and see **every dispensary that carries it, side by side,
sorted by price**, then click through to that dispensary's site to buy.

> "Any dispensary that has a Stiiizy vape pod 1g in whatever the strain would be,
> the system pulls up the dispensaries that have it in a side-by-side comparison,
> and the link redirects the user to their website to purchase."

**Guiding principle (non-negotiable):** *Accuracy over coverage. A missed match
is better than a false match.* Never assume two products are the same just
because they share a brand, category, and size. Identity precision is the moat.

---

## 2. Users & Core Use Cases

- **Shopper (primary):** searches "Blue Dream 1g pod" → sees a single canonical
  product card → expands to a price-ranked list of dispensaries carrying it →
  clicks out to purchase.
- **Operator / data curator (internal):** works the review queue, approves brand
  and product aliases, confirms/rejects near-matches. Their decisions
  permanently strengthen the matching engine.
- **Dispensary (indirect):** receives qualified click-through traffic from
  price-competitive listings.

---

## 3. System Architecture (end to end)

```
                 multiple times/day, per dispensary
  ┌─────────────┐   harvest    ┌──────────────┐  raw rows   ┌──────────────┐
  │ Dispensary  │ ───────────▶ │  Scraper     │ ──────────▶ │  Raw store   │
  │ menus       │  platform    │  engine      │  preserved  │ (RawDPL)     │
  │ (11 APIs)   │  adapters    │ (curl_cffi)  │  payload    │              │
  └─────────────┘              └──────────────┘             └──────┬───────┘
                                                                    │
                                                          normalize (per row)
                                                                    ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │ Normalization engine (pek_engine)                                      │
  │  text clean → eligibility gate → category → form/hardware → brand      │
  │  → product identity → size/mg → extract/infusion → PEK                 │
  └───────────────┬──────────────────────────────────────────────────────┘
                  │ exact PEK groups
                  ▼
  ┌──────────────────────┐   hard gates    ┌────────────────────────────┐
  │ Master Canonical      │ ◀────────────── │ Near-match analysis +      │
  │ Products (MCP)        │  veto bad merge │ embeddings recall layer    │
  └──────────┬───────────┘                 └─────────────┬──────────────┘
             │                                            │ uncertain
             │ priced + linked                            ▼
             ▼                                  ┌────────────────────┐
  ┌──────────────────────┐                      │ Review queue +     │
  │ Price comparison index│                     │ alias suggestions  │
  │ (search + side-by-side)│                    └─────────┬──────────┘
  └──────────────────────┘                                │
             ▲                                             ▼
             │ stronger tables next batch        ┌────────────────────┐
             └─────────────────────────────────  │ Product agent      │
                  approved aliases / rejections   │ (LLM + human)      │
                                                  └────────────────────┘
```

Four subsystems:
1. **Scraper engine** — multi-platform menu harvesters → raw listings.
2. **Normalization engine** — raw listing → canonical identity (PEK) → MCP.
3. **Product agent** — human-in-the-loop adjudication loop that learns aliases.
4. **Search / price-compare surface** — query → MCP → ranked dispensary list.

**The learning loop:** scrape → normalize → match → (uncertain) review →
agent + human approve aliases / record rejections → those decisions feed the
alias and rejected-match tables → next batch the deterministic engine matches
more, with the same precision. The engine gets smarter without ever loosening
the hard gates.

---

## 4. Subsystem A — Scraper Engine

### 4.1 Goals
- Harvest each dispensary's full live menu, **multiple times per day**.
- Support every platform in the registry: **Dutchie, Carrot, Jane, Blaze,
  Weedmaps, AIQ/Dispense, Proteus420, Treez, KushMart, Flowhub** (extensible).
- **Preserve the raw payload** exactly (audit + re-normalization without re-scrape).
- Be polite and resilient: per-platform rate limits, retries, browser
  impersonation (`curl_cffi`) to pass anti-bot, graceful per-store failure.

### 4.2 Design
- A **registry** (`dispensaries.csv` → `DispensaryRegistry`) maps each store to
  `(platform, external_id, menu_url)`. `external_id` format is platform-specific
  (Dutchie: dispensary GUID; Carrot: `host|api_key|index`; Weedmaps: slug; …).
- One **adapter per platform** with a uniform signature
  `fetch(external_id, **opts) -> list[RawProduct]`. Adapters are thin wrappers
  over each platform's public menu API (endpoints proven in the user's script).
- A **runner** iterates the registry, routes each store to its adapter, maps the
  platform payload into the canonical **raw-listing schema** (the exact shape the
  normalization engine ingests), and writes to a **sink**.
- **Sinks:** JSON file (default, feeds `run.py` directly) and Postgres
  (`dispensary_products` upsert table, `ON CONFLICT DO UPDATE`). Pluggable.
- **Offline/fixture mode:** adapters can read recorded JSON fixtures instead of
  the network, so parsing logic is unit-tested deterministically and the whole
  pipeline runs without internet.

### 4.3 Canonical raw-listing schema (scraper output == engine input)
```json
{
  "dispensary": "Canterra", "dispensary_id": "64d2683c...",
  "product_id": "69cab853...", "title": "...", "brand": "...",
  "category": "...", "original_type": "...", "original_subcategory": "...",
  "strain_type": "...", "thc": "...", "thc_unit": "...", "cbd": "...",
  "cbd_unit": "...", "weight": "...", "price": "...", "image": "...",
  "product_url": "...", "platform": "Dutchie", "scraped_at": "ISO-8601"
}
```
`product_url` (new) is built from the menu URL + product id where the platform
exposes it, giving the "click out to buy" link the price-compare view needs.

### 4.4 Scheduling
- Cron / scheduler triggers full harvest **N× per day** (configurable; default 3).
- Each harvest is a **batch** (`batch_id`) so price history is queryable over time.
- Stores are harvested concurrently with a bounded worker pool + per-platform
  throttle. A store failure is logged and skipped, never aborts the batch.

### 4.4a Incremental harvest (delta engine)
The menu APIs expose no universal "changed-since" feed, so a pull still asks each
store for its current menu. But everything downstream is incremental:
- Each product is reduced to a **content fingerprint** (hash of the meaningful
  fields, excluding volatile bookkeeping). Comparing to the per-dispensary
  snapshot from the last pull classifies every product as
  **added / changed / removed / unchanged**.
- Only **added + changed** rows flow downstream to re-normalization; **removed**
  product ids are recorded (delisted / out of stock); **unchanged** rows are
  never re-normalized or rewritten — their MCP links and price rows carry forward.
- Every price move appends one row to an append-only **price-event log**.
- CLI: `scrape --incremental --state-dir state --delta delta.json
  --price-history price_history.jsonl`; then `normalize --incremental --prev
  <last_out> --delta delta.json`.
- Where a platform supports an updated/sort cursor, pagination can short-circuit
  once it reaches unchanged older pages (Dutchie sort hooks present).

### 4.4b Time-series archival (analytics without bloat)
Storing full snapshots (≈25k products × N pulls/day × 365) is wasteful and
mostly redundant. Because **a price is a step function**, the entire history is
reconstructable from just the change-points, so we keep tiered, compacting data:
- **Tier 0 — current_state:** one row per live product (overwritten each pull).
- **Tier 1 — events:** append-only, only on change. Lossless for price trends.
  Full granularity retained ~90 days.
- **Tier 2 — daily rollup:** OHLC (open/high/low/close/avg, # changes) per
  `(mcp_id, dispensary, day)` — only days with a change. Kept ~13 months.
- **Tier 3 — monthly rollup:** per `(mcp_id, dispensary, month)`; kept for years.
- **Compaction** (`archive` subcommand) folds events older than the retention
  window into the daily rollup (and daily into monthly), so storage stays roughly
  constant rather than growing linearly with pulls.
- Analytics key off the **canonical MCP id** (not per-store product GUIDs, which
  explode cardinality); prices stored as integer **cents**.

### 4.5 Non-functional
- Anti-bot: `curl_cffi` with `impersonate="chrome*"`; rotate UA/headers per
  platform; backoff on 429/403.
- Idempotent: re-running a batch updates rows, never duplicates (id =
  `external_id + platform_product_id`).
- Observability: per-store item counts, error log, batch summary.
- Legal/ToS: harvest only public menu data; respect robots/ToS; throttle.

---

## 5. Subsystem B — Normalization Engine (implemented)

See `docs/normalization_foundation_v1.txt` for the full spec. Summary:

- **DPL** = one raw listing (immutable). **MCP** = one canonical product.
  **PEK** = deterministic identity fingerprint built only from identity fields.
- Pipeline: text clean → cannabis eligibility gate → 7 canonical categories →
  form/subform/hardware → brand (alias table + title-prefix) → product identity
  (strip brand/size/form/extract/descriptors) → size grams or edible mg+ratio →
  extract/infusion → **PEK**.
- **Matching:** identical PEK → auto-merge. **Hard gates** veto merges across
  conflicting extract / hardware / size / ratio (cart≠disposable, live
  resin≠live rosin, 0.5g≠1g, 1:1≠2:1). Missing field on one side → review, never
  force-merge.
- **Candidate generators propose, gates dispose.** A dependency-free char-n-gram
  **embeddings recall layer** surfaces near pairs the exact-product bucket missed;
  every candidate still passes the hard gates before being suggested. Pluggable
  for a transformer model later. Brand resolution also suggests the nearest
  approved brand for unknown brands.
- **Outputs:** normalized DPLs, MCPs, links, price comparison index, review
  queue, rejected near-matches, data-quality flags, brand/product alias
  suggestions, batch summary.

### 5.1 Why not match on image or product_id?
- `product_id` is per-store unique → useless across dispensaries.
- Image URLs are reused, but **mostly at the brand/product-line level** (1,217
  shared-image groups span multiple distinct products vs. 469 that map 1:1, ~28%
  precision) → image is used as the **canonical photo + weak corroboration only**,
  never as a merge key.

---

## 6. Subsystem C — Product Agent (the learning loop)

**Thesis:** full automation is not the endgame. The system gets accurate by
**accumulating human-approved decisions**, not by trusting a model's guess.

Three tiers:
1. **Deterministic core** (PEK + hard gates): high precision, auto-merge only
   when certain. Never guesses.
2. **Candidate generators** (embeddings, fuzzy, image corroboration): only
   *propose* pairs into the review queue.
3. **Product agent** (LLM-assisted + human approval): adjudicates the queue,
   emits **structured decisions** with rationale + evidence, and writes approved
   decisions into the alias + rejected-match tables. Those feed tier 1 next batch.

### 6.1 Decision contract
The agent consumes `review_queue`, `brand_alias_suggestions`,
`product_alias_suggestions`, and `rejected_near_matches`, and emits
`AgentDecision` records:

```python
AgentDecision = {
  "decision_id": str,
  "kind": "brand_alias" | "product_alias" | "merge" | "split" |
          "fix_field" | "reject",
  "subject": {... ids / values ...},
  "verdict": "approve" | "reject" | "needs_human",
  "confidence": float,           # 0..1
  "rationale": str,              # human-readable why
  "evidence": [str],             # signals used (PEK parts, similarity, image…)
  "writes_to": "brand_aliases" | "product_aliases" | "rejected_matches" | None,
  "requires_human": bool,        # always true unless confidence >= auto_threshold
}
```

### 6.2 Gating rules (mirror the engine's philosophy)
- The agent **never overrides a hard gate.** If `_classify_conflict` says two
  MCPs conflict on extract/hardware/size/ratio, the agent can only `reject` (and
  record the rejection), never `merge`.
- Default `verdict` requires **human approval** (`requires_human = true`). Only
  brand/product *alias* decisions above an `auto_threshold` may auto-apply, and
  even then they are reversible and logged.
- Every approved alias is written to the editable alias tables; every confirmed
  non-match is written to rejected-match **memory** so it is never re-proposed.

### 6.3 Backends (pluggable)
- `HeuristicBackend` (default, offline): deterministic rules over the available
  signals (string similarity, shared brand/size/form, embedding score). No API
  key required; used for tests and as a fallback.
- `LLMBackend` (optional): sends the candidate + evidence to an LLM that returns
  a structured decision + rationale. Reasons about domain nuance ("Blueberry 2.0
  == Blueberry #2 *for this brand*"). Requires an API key; output is still a
  suggestion gated by the hard gates and (by default) human approval.

---

## 7. Subsystem D — Search & Price Comparison (surface)

- **Query → canonical product:** free-text search resolves to MCP(s). v1 =
  token/alias lookup over MCP titles; v2 = embedding nearest-neighbor (the recall
  layer already exists, reused for search where there is no false-merge risk).
- **Side-by-side view:** for the chosen MCP, list every linked dispensary with
  price, distance (future), stock (future), and a **buy link** (`product_url`),
  sorted by price. This is the `price_comparison_index` output.
- **Price history:** because each harvest is a batch, the index supports price
  trends per product per dispensary over time (future).

---

## 8. Data Model (logical)

- `dispensary(id, name, platform, external_id, menu_url, …)`
- `raw_dpl(raw_dpl_id, dispensary_id, batch_id, payload JSON, scraped_at, …)`
- `normalized_dpl(… all normalized fields, proposed_pek, confidence, status)`
- `mcp(mcp_id, pek, canonical_title, identity fields, review_status)`
- `mcp_dpl_link(mcp_id, raw_dpl_id, match_method)`
- `price_index(mcp_id, dispensary_id, price, product_url, batch_id, scraped_at)`
- `brand_alias(alias, canonical_brand, approved_by, approved_at)`
- `product_alias(brand, value_a, value_b, approved_by, approved_at)`
- `rejected_match(mcp_id_1, mcp_id_2, reason, rule_learned)`
- `review_item(…)`, `data_quality_flag(…)`, `agent_decision(…)`

Phase-1 ships these as JSON outputs using the spec's field names; the same
schema maps directly to the Postgres DDL for production.

---

## 9. Phased Roadmap

- **Phase 1 — Normalization core (DONE):** raw → PEK → MCP → price index +
  review/rejected/flags/suggestions. 19,644 listings → ~14k MCPs, ~2.6k
  multi-dispensary. Embeddings recall + fuzzy brand suggestions. 10 tests.
- **Phase 2 — Scraper engine (THIS PR):** multi-platform adapters, registry,
  runner, sinks, fixture mode. Scrape → normalize is one continuous pipeline.
- **Phase 3 — Product agent (THIS PR):** decision contract, heuristic + LLM
  backends, write-back into alias/rejected tables.
- **Phase 4 — Incremental harvest + archival (THIS PR):** delta engine
  (added/changed/removed/unchanged), incremental normalize, append-only price
  events, tiered daily/monthly rollups + retention compaction. Remaining for a
  later pass: Postgres sink for the rollups + a cron scheduler.
- **Phase 5 — Search surface / API + UI:** query → MCP → side-by-side compare →
  buy link; embedding search; distance/stock.

---

## 10. Success Metrics

- **Match precision** (sampled): false-merge rate near zero (the hard gate).
- **Coverage:** % of eligible listings linked to an MCP; multi-dispensary MCP count.
- **Curation throughput:** review items resolved per operator-hour; alias table growth.
- **Freshness:** harvest success rate per platform; menu staleness (time since
  last successful scrape).
- **Shopper outcome:** search → product → click-out conversion.

---

## 11. Risks & Open Questions

- **Anti-bot / ToS:** platforms may block automated harvesting; mitigated via
  `curl_cffi` impersonation + throttling, but resilience per platform varies.
- **Missing registry fields:** several `Platform Store ID`s in the CSV are blank
  (Proteus420, AIQ, Jane, Blaze, KushMart) and must be filled before those
  adapters can run live.
- **No cross-platform shared key:** matching must rely entirely on normalized
  identity; this is by design but raises the bar on normalization quality.
- **LLM cost/latency & hallucination:** the agent gates every LLM output behind
  the hard gates + human approval; LLM is an accelerator, not an authority.
