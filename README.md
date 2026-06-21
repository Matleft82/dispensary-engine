# Dispensary Price-Comparison Engine

Turns messy dispensary menu listings into clean, comparable **canonical products**
so the same real-world product can be priced side-by-side across dispensaries.

Implements **Normalization Foundation v1**: *normalize aggressively, match
conservatively*. A missed match is better than a false match. Source data is
never mutated and missing facts are never fabricated.

Three subsystems live in `pek_engine/`:
- **`scrape/`** — multi-platform menu harvesters → raw listings.
- normalization core (root modules) — raw listing → PEK → MCP → price index.
- **`agent/`** — human-in-the-loop adjudicator that turns uncertain matches into
  approved brand/product aliases + rejections feeding the core next batch.

The full product spec is in [`docs/PRD.md`](docs/PRD.md).

## Core concepts

| Term | Meaning |
|---|---|
| **DPL** | Dispensary Product Listing — one raw row from one menu (source truth) |
| **MCP** | Master Canonical Product — the clean product card shown to shoppers |
| **PEK** | Product Equality Key — the deterministic fingerprint used to decide if two listings are the same product |

A PEK is built from normalized identity fields (brand, category, form, subform,
size, product name, extract type, infusion type, hardware, count, mg, ratio) and
**never** from price, dispensary, stock, or menu IDs.

## Pipeline

`raw menu → raw DPL → clean text → cannabis eligibility gate → category →
form/subform/hardware → brand → product identity → size/mg → extract/infusion →
PEK → exact-PEK grouping → hard-gate near-match analysis → MCP →
review queue / rejected near-matches → price comparison index`

See [`docs/`](docs) for the full spec and design notes.

## Run

The CLI has three subcommands (`normalize` is the default for backward compat):

```bash
# 1. Harvest live menus -> raw listings (needs the `scrape` extra for anti-bot)
python run.py scrape --dispensaries data/dispensaries.csv --out data/raw_listings.json
#    optional: --platforms dutchie,carrot   --limit 5

# 2. Normalize raw listings -> MCPs + price comparison index
python run.py normalize --raw data/raw_listings.json \
  --brands data/brand_aliases_seed.csv \
  --dispensaries data/dispensaries.csv --out outputs

# 3. Adjudicate uncertain matches -> agent decisions (+ optionally apply aliases)
python run.py agent --out outputs --data data --apply
```

### Incremental pulls (don't re-download/re-process unchanged products)

Scheduled re-pulls should only act on what changed. The delta engine fingerprints
every product, diffs against the last pull's per-dispensary snapshot, and routes
only the changes downstream (unchanged products are never re-normalized).

```bash
# Incremental harvest: writes the current snapshot + a delta (added/changed/removed)
# + appends every price move to an append-only event log.
python run.py scrape --incremental --state-dir state \
  --delta data/delta.json --price-history outputs/price_history.jsonl \
  --out data/raw_listings.json

# Incremental normalize: re-normalizes only the delta, carries the rest forward.
python run.py normalize --incremental --prev outputs \
  --delta data/delta.json --out outputs

# Archive for time-series analytics: map events -> canonical MCP, build
# current_state, and compact old events into daily/monthly OHLC rollups.
python run.py archive --out outputs --archive-dir archive \
  --price-history outputs/price_history.jsonl --recent-days 90 --daily-months 13
```

A price is a step function, so the change-event log is a **lossless** record of
price-over-time at a tiny fraction of the storage of full snapshots. Compaction
keeps the raw event log bounded by folding old events into daily then monthly
rollups, so archival storage stays roughly constant instead of growing linearly
with pulls. See `docs/PRD.md` §4.4a–4.4b.

### Scheduling the N×/day cadence + Postgres archive

`schedule` runs the whole cycle (scrape → normalize → archive) on a cadence. The
first tick seeds a full normalize; every later tick only processes the delta.
Pass `--dsn` (on `archive` or `schedule`) to load the archive tiers into Postgres
— `current_state`, `price_events` (append-only, deduped → idempotent),
`daily_rollup`, `monthly_rollup`, keyed on MCP id with prices in cents. Requires
the `db` extra (`pip install -e ".[db]"`); the same SQL runs on SQLite for tests.

```bash
# Long-lived loop: 3 harvests/day, jittered, persisting to Postgres
python run.py schedule --times-per-day 3 --jitter 600 \
  --dsn postgresql+psycopg2://user:pass@host/dbname

# Single tick — wire to system cron (every 8h):
#   0 */8 * * *  cd /srv/engine && python run.py schedule --once --dsn $PG_DSN
python run.py schedule --once --platforms dutchie,weedmaps \
  --dsn postgresql+psycopg2://user:pass@host/dbname

# Or just load an already-compacted archive into Postgres:
python run.py archive --out outputs --archive-dir archive --dsn $PG_DSN
```

### Scraper engine (`pek_engine/scrape/`)

Registry-driven (`dispensaries.csv`) multi-platform harvesting. Adapters cover
**Dutchie, Carrot, Jane, Blaze, Weedmaps, AIQ/Dispense, Flowhub** (Proteus420 /
KushMart / Treez are HTML scrapers, stubbed behind the same interface). Each
adapter emits the exact raw-listing schema the normalizer ingests, so
scrape→normalize is one pipeline. Network I/O goes through an injectable client
(`HttpClient` with `curl_cffi` impersonation, `urllib` fallback, or a
`FixtureClient` for offline tests). Sinks: JSON file (default) or Postgres.

> Live harvesting depends on the host IP not being anti-bot-blocked and on the
> registry's `Platform Store ID`s being filled (several are blank). Install
> `pip install -e .[scrape]` for browser impersonation. Adapter parsing is
> covered by offline fixture tests regardless of network access.

### Product agent (`pek_engine/agent/`)

Adjudicates `review_queue` + alias suggestions into structured `AgentDecision`s
(approve/reject alias, fix-field, reject-merge) with rationale + evidence.
**It never overrides a hard gate** — a conflict can only be rejected. Decisions
default to requiring human approval; only high-confidence aliases auto-apply and
are written back to the editable alias / rejected-match tables. Backends are
pluggable: `HeuristicBackend` (offline default) and `LLMBackend` (optional,
takes a user-supplied `llm_fn`, falls back to heuristic on any failure).

Outputs (in `outputs/`, mirroring the spec's tables):

| File | Contents |
|---|---|
| `normalized_dpls.json` | Every listing with all normalized fields + PEK |
| `master_canonical_products.json` | The canonical product cards (MCPs) |
| `mcp_dpl_links.json` | Which listings map to which MCP, with confidence + method |
| `price_comparison_index.json` | Per-listing price rows keyed by MCP (the search/compare view) |
| `review_queue.json` | Uncertain matches needing human review, with reasons |
| `rejected_near_matches.json` | "Looks similar but must not merge" learnings |
| `data_quality_flags.json` | Missing/suspicious source data |
| `brand_alias_suggestions.json` | New brand spellings not in the approved table |
| `product_alias_suggestions.json` | Brand-scoped fuzzy product-name candidates |
| `batch_summary.json` / `batch_summary.md` | Batch report (counts + top comparisons + review sample) |

## Tests

```bash
pip install pytest
pytest -q
```

Tests are anchored on the spec's worked examples (live resin ≠ live rosin, cart ≠
disposable, descriptor words must not split product identity, etc.).

## Design notes & current limitations

- **Matching is exact-PEK first.** Listings with an identical PEK collapse into
  one MCP. Listings that share brand/category/product but differ on a hard-gate
  field (extract, hardware, infusion, size, ratio) become either a *rejected
  near-match* (both sides state a conflicting value) or a *review candidate*
  (one side is missing the field).
- **Brand aliases** come from `brand_aliases_seed.csv` (treated as approved).
  Unrecognized brands resolve to a cleaned display name **and** are emitted to
  `brand_alias_suggestions.json` for human approval — never auto-merged.
- **Product/flavor aliases** are only ever *suggested* (brand-scoped), never
  auto-applied (per spec).
- **Source data gaps:** the current feed has no description, sale price, stock,
  product URL, or UPC. Extract/form/infusion/mg are parsed from title +
  subcategory only. Image-based contradiction detection is a future hook (needs
  image download + OCR).
- **Pre-roll weight ambiguity:** a gram value ≤ 1g with a pack count is treated
  as per-unit (`5pk 0.5g`); larger values are treated as the pack total
  (`5 pack 3g`). Normalized consistently so identical listings still match.

## Roadmap

1. **Normalization core** ✅
2. **Scraper engine** (multi-platform adapters, registry, sinks) ✅
3. **Product agent** (adjudication loop + write-back to alias tables) ✅
4. Persistence (Postgres) + scheduled multi-daily harvests + price history
5. Search + side-by-side comparison web app (free-text → MCP → ranked dispensaries → buy link)

See [`docs/PRD.md`](docs/PRD.md) for the full phased plan.
