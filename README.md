# Dispensary PEK / MCP Engine

Turns messy dispensary menu listings into clean, comparable **canonical products**
so the same real-world product can be priced side-by-side across dispensaries.

Implements **Normalization Foundation v1**: *normalize aggressively, match
conservatively*. A missed match is better than a false match. Source data is
never mutated and missing facts are never fabricated.

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

```bash
python run.py \
  --raw data/raw_listings.json \
  --brands data/brand_aliases_seed.csv \
  --dispensaries data/dispensaries.csv \
  --out outputs
```

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

1. **Normalization core** (this package) ✅
2. Scrapers per platform (Dutchie, Carrot, AIQ, Jane, …) feeding the raw DPL table
3. Persistent store (Postgres) using the spec DDL + human review UI
4. Search + comparison web app
