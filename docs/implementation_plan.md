# PEK / MCP Normalization Engine — Implementation Plan

Based on **Normalization Foundation v1** + the provided data. This is a plan only — no code written yet.

---

## 1. What the data actually is

| File | What it is | Notes |
|---|---|---|
| `normalized_products3.json` | **The raw input** — 19,644 listings (DPLs) from 38 dispensaries | Despite the name, this is *un*-normalized source truth |
| `product_comparison_engine2.json` | An **existing v2 engine output** — 16,390 comparison keys | Uses a coarse key; demonstrates the over/under-splitting problems the spec fixes |
| `brand_aliases3.csv` | 312 canonical brands → `canonical_brand, aliases` (pipe-separated) | Seed for the `brand_aliases` table |
| `YAY_-_Sheet1.csv` | Dispensary directory (name, address, platform, store id, menu URL) | Source/dispensary metadata |
| `Engine_Dev*.txt` (9 files) | Scraper docs/code per platform (AIQ, BLAZE, CARROT, DUTCHIE, ETHER, GOODLIFE, JANE, KUSHMART, PROTEUS420) | Ingestion side — **assumed out of scope** for this build |
| `Normalization_Foundation_v1...docx` | The full spec (SQL schemas + pipeline) | Source of truth for the design |

### Fields available per listing (the real constraint)
`dispensary, dispensary_id, product_id, title, brand, category, original_type, original_subcategory, strain_type, thc, thc_unit, cbd, cbd_unit, weight, price, image`

**Missing vs. what the spec assumes:** `description`, `sale_price`, `stock_status`, `product_url`, `scraped_at`, `UPC`. Implications:
- Extract / infusion / hardware / form / count / mg must be parsed almost entirely from **`title` + `original_subcategory`** (no description to lean on).
- Image-based contradiction detection (spec mentions it) is **not feasible** without downloading + OCR'ing images — I'll flag it as a future hook, not build it now.
- Price comparison index will have `price` + `effective_price` but no real `sale_price`/`stock` unless you have richer source data.

### Dataset profile
- 38 dispensaries, platforms = **Dutchie + Carrot**.
- 626 distinct raw brand strings; 136 listings with blank brand → title-prefix extraction needed.
- Raw categories are messy/duplicated: `Pre-Rolls` + `Preroll`, `Carts` + `Vaporizers` + `Disposables`, `Edible(s)` + `Beverages`, `Concentrate(s)`, `Topical(s)`, `Accessories`, `Merch`. Folding required.
- THC units mixed: PERCENTAGE (13,574), blank (3,646), MILLIGRAMS (2,419), per-gram/per-ml (5).
- Weight is noisy: `1g`, `.1g`, `1.0`, `1/8oz`, `3.5`, `10.0mg`, blanks. The `.1g`/`.01g` edible artifacts the spec warns about are present (1,901 `.1g`).

### Concrete defect the new PEK fixes (from existing engine)
The v2 keys split the same product because a descriptor leaked into identity:
- `#hash|angie sativahybrid wax budder|1g|concentrates`
- `#hash|angie wax budder|1g|concentrates`
Same product (Angie Wax Budder, #Hash, 1g) → 2 keys. Conversely the coarse key would **merge** a Live Resin cart with a Distillate cart. The spec's PEK (form + extract + infusion + hardware + count) fixes both directions.

---

## 2. Proposed deliverable

A self-contained **Python package** that runs offline on `normalized_products3.json` and produces the spec's tables as outputs. Concretely:

```
pek_engine/
  ingest.py            # raw DPL load (preserve source truth + raw_payload)
  text_clean.py        # title/brand text normalization, decoration stripping
  eligibility.py       # cannabis gate (accessory/merch exclusion)
  category.py          # raw category -> canonical (7 buckets)
  form.py              # form / subform / hardware detection
  brand.py             # alias table load + brand resolution + title-prefix fallback
  product_name.py      # strip brand/size/form/descriptors -> identity
  size.py              # grams / count / total-weight parsing
  edible_mg.py         # package/serving mg, ratio, cannabinoid profile, artifact ignore
  extract_infusion.py  # extract_type / infusion_type normalization
  pek.py               # per-category PEK construction
  matching.py          # hard gates + scoring + auto/review/new-MCP decision
  mcp.py               # MCP creation + canonical title builder
  review.py            # review queue + rejected-near-match + data-quality flags
  pipeline.py          # orchestrates steps 1-23 from the spec
  rules/               # editable lookup data (categories, forms, extract, units, aliases)
data outputs (JSON, + optional SQLite mirroring the spec DDL):
  normalized_dpls.json
  master_canonical_products.json
  mcp_dpl_links.json
  price_comparison_index.json
  review_queue.json
  rejected_near_matches.json
  data_quality_flags.json
  brand_alias_suggestions.json / product_alias_suggestions.json
  batch_summary.json / batch_summary.md
```

Design principles from the spec I'll hold to:
- **Normalize aggressively, match conservatively.** False match >> missed match.
- **Never mutate raw data**; everything reproducible from raw + rule tables.
- **Deterministic, explainable PEK**; blank fields stay blank, never fabricated.
- **Hard gates before scoring**; a high score can't override a gate conflict.
- Lookup/rule tables live in editable files so the brand/category/alias logic can grow without code changes.

---

## 3. Pipeline (mapping to spec §27)

1. **Ingest** raw rows → preserve every source field + full `raw_payload`; assign `raw_dpl_id`, `batch_id`.
2. **Text clean** title/brand/category (apostrophes, dashes, whitespace, unicode; strip SALE/NEW/Staff Pick decorations; keep display + search variants).
3. **Eligibility gate** → set `comparison_status` (`eligible_cannabis` vs `excluded_accessory/merchandise/non_cannabis`). Accessories/Merch get no PEK/MCP.
4. **Category** fold to 7 canonical buckets (Flower, Pre-Rolls, Vapes, Concentrates, Edibles, Topicals, Tinctures). Use title + subcategory, not just `category`, since the title "knows more."
5. **Form / subform / hardware** (510 Cartridge vs Disposable vs AIO vs Pod; Gummy vs Beverage vs Capsule; Hash Hole/Blunt subforms; Small Buds; RSO syringe).
6. **Brand** resolve via alias table (Level 1 auto-format, Level 2 approved aliases) → `normalized_brand` + `brand_confidence`; blank-brand → title-prefix extraction with confidence gating.
7. **Product name / strain / flavor** = title minus brand/size/form/extract/infusion/hardware/THC/labels/**descriptors** (indica/sativa/hybrid/live resin/premium/etc.). This is where the `#hash` defect gets fixed.
8. **Size**: grams + count + unit/total weight for flower/pre-roll/vape/concentrate; **mg/serving/ratio/profile** for edibles & tinctures; ignore `.1g/.01g` edible gram artifacts.
9. **Extract / infusion** normalization (Live Resin ≠ Live Rosin, Rosin ≠ Resin, Unknown ≠ known).
10. **Generate PEK** per category template (spec §18).
11. **Match**: exact PEK → link; else hard gates (§19 gates 1–10) → score (§20 bands) → auto-link / review / provisional new MCP.
12. **MCP create** with readable canonical title (spec §21).
13. **Review queue / rejected near-matches / data-quality flags** populated with side-by-side fields + reasons.
14. **Price comparison index** for eligible+linked+priced listings.
15. **Batch summary** in the spec's required format (§ "Batch Summary Format").

---

## 4. Key risk areas (where accuracy is won or lost)

- **Product-name extraction** is the hardest part — getting descriptors out without eating real identity words (e.g. "Blue Dream" vs "blue" descriptor). Will be rule + token based, conservative, with anything ambiguous → review, not auto-merge.
- **Brand-scoped product aliases**: only suggested, never auto-applied (spec rule). Output as suggestions.
- **Weight ambiguity** (`1.0`, `3.5` with no unit) → infer unit from category context; if unsafe, leave size blank + `missing_size` flag → review rather than guess.
- **mixed THC units / mg parsing** for edibles from title text only.

---

## 5. Open questions before I build

1. **Deliverable format** — Python package emitting JSON outputs (+ optional SQLite using the spec's exact DDL)? Or do you want a live Postgres schema + loaders? Or just the JSON outputs?
2. **Repo / location** — New git repo (which org/name)? Existing repo? Or just hand back files/zip in this session?
3. **Scope of this iteration** — Run the full pipeline over the existing 19,644-listing dataset and produce all tables + batch summary + review queue. Are the platform **scrapers (Engine_Dev*.txt) out of scope** for now (I'm assuming yes)?
4. **Brand alias seed** — Treat `brand_aliases3.csv` as the pre-approved `brand_aliases` table (status `approved`)? New ones I detect go to `brand_alias_suggestions` for your review, not auto-applied — correct?
5. **Output language/stack** — Python OK? Any constraints (must be SQL-only, must match an existing codebase style, etc.)?
