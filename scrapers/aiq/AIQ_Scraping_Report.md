# Scraping AIQ Dispensary Menus — Developer Report

**Scope:** The three AIQ dispensaries in the master list.
**Verified:** 2026-06-23. All endpoints/headers below were hit live against the production API and returned `200`.

---

## 1. TL;DR

AIQ menus are served by **Dispense** (`api.dispenseapp.com`). The storefront at
`menus.dispenseapp.com/{venue_id}/menu` is a thin client that calls a **public JSON REST API**.
There is **no per-store auth, no login, no user token** — you only need:

1. A single shared, hard-coded **`api-key`** (same value for every Dispense storefront).
2. A small set of **origin/referer headers** so the request looks like it came from the menu site.
3. A **TLS/JA3 fingerprint that looks like a real Chrome browser** — both the CDN and the API sit behind Cloudflare and will block a plain `requests`/`httpx` client. Use **`curl_cffi` with `impersonate="chrome124"`** (or Playwright). This is the single most important detail.

Once those are in place the flow is: list categories → page through each category's products → de-duplicate → normalize.

### The three venues

| Dispensary | `venue_id` | Menu URL | Categories | Unique products (verified) |
|---|---|---|---|---|
| 82-J Cannabis Company | `390243df4f0ee7fa` | https://menus.dispenseapp.com/390243df4f0ee7fa/menu | 11 | ~156 |
| Innocence Cannabis | `0d177a4c05c521ca` | https://menus.dispenseapp.com/0d177a4c05c521ca/menu | 12 | ~122 |
| Mrs. Green's Cannary | `74422ea119bfc60b` | https://menus.dispenseapp.com/74422ea119bfc60b/menu | 12 | ~908 |

> The same scraper works unchanged for **any** Dispense/AIQ store — just swap the `venue_id`.
> You can read a store's `venue_id` straight out of its menu URL.

---

## 2. Endpoints

Base URL: `https://api.dispenseapp.com`

| Purpose | Method & Path | Notes |
|---|---|---|
| Venue / store metadata | `GET /v1/venues/{venue_id}` | Name, address, timezone, hours, tax config, POS type, branding. Optional but useful. |
| List product categories | `GET /v1/venues/{venue_id}/product-categories?orderPickUpType=IN_STORE` | Returns the menu's category tabs. |
| List products in a category | `GET /v1/venues/{venue_id}/product-categories/{category_id}/products?orderPickUpType=IN_STORE&limit=200&skip=0` | The actual menu data. Paginate with `skip`/`limit`. |

All responses are JSON of the shape `{ "data": <object | array>, ... }`. The product/category list
endpoints return their rows under `data`. **The product list endpoint returns NO pagination metadata**
(no total count, no `hasMore`) — you page until a batch comes back with fewer than `limit` rows (see §4).

### Query params
- `orderPickUpType=IN_STORE` — required-ish; selects the in-store menu/pricing context. (`PICKUP`, `DELIVERY` also exist and can change availability/pricing.)
- `limit` — page size. **200 works reliably**; treat it as the max.
- `skip` — offset for pagination.

---

## 3. Authentication & headers (the part that matters)

There is **no OAuth, no bearer token, no per-store secret.** Access is gated only by a shared API key
+ Cloudflare's bot check. Send these headers on every call:

```
api-key:          49dac8e0-7743-11e9-8e3f-a5601eb2e936
x-pathname:       <the API path you are calling, e.g. /v1/venues/{venue_id}/product-categories>
x-url:            https://menus.dispenseapp.com/{venue_id}/menu
Origin:           https://menus.dispenseapp.com
Referer:          https://menus.dispenseapp.com/
Accept:           application/json
Accept-Language:  en-US,en;q=0.9
User-Agent:       Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36
```

Notes / gotchas:
- **`api-key` is a public client key** baked into the Dispense storefront JS — the same value for all
  Dispense stores. It can rotate; if you start getting `401/403`, re-grab it from the menu site
  (DevTools → Network → any `api.dispenseapp.com` XHR → Request Headers → `api-key`).
- **`x-pathname` / `x-url`** are sanity headers the API/WAF expects from the SPA. Set `x-pathname` to the
  exact path of the request you're making. Missing or wrong values can trigger blocks.
- **TLS fingerprint is enforced.** A normal Python HTTP client (correct headers and all) still gets
  blocked by Cloudflare. `curl_cffi`'s `impersonate="chrome124"` replicates Chrome's JA3/HTTP2
  fingerprint and passes. Plain `requests`, `urllib`, and `httpx` do **not** work.

---

## 4. Pagination

Per category:

```
skip = 0
loop:
    GET .../products?orderPickUpType=IN_STORE&limit=200&skip=skip
    batch = response["data"]
    if batch is empty: stop
    keep batch
    if len(batch) < 200: stop      # last page
    skip += 200
```

There is no `total`/`hasMore` field, so the only reliable stop condition is "a short page". Several
categories (e.g. Mrs. Green's `Flower`, `Pre Rolls`, `Vaporizers`) return full 200-row pages and
genuinely need a second/third page.

---

## 5. De-duplication (important)

Products are returned **per category**, and the same product appears in multiple categories. Specifically:

- Every store has an **`Offers` / `Specials`** category (category `type` = `OFFERS`) that re-lists
  discounted products that *also* live in their real category (Flower, Edibles, …).
- Across Mrs. Green's, raw rows summed to **1,810** but there are only **~908 unique** products — i.e.
  roughly half the rows are duplicates, almost all from `Specials`.

**De-dupe on the product `id`** (equivalently `_id`; they're identical) as you ingest. Keep the first
occurrence, or prefer the occurrence from a non-`OFFERS` category if you want the "home" category name.

Category `type` values observed: **`OFFERS`** (the specials tab) and **`SYSTEM`** (real menu categories).
Filter or flag `type == "OFFERS"` if you want to know which products are on special.

---

## 6. The product object (the schema)

Each product is a flat-ish JSON object. The fields that matter for a menu/price/inventory scrape:

### Identity
| Field | Type | Meaning |
|---|---|---|
| `id` / `_id` | string | Stable product id. **De-dupe key.** (both are the same value) |
| `sku` | string | POS SKU |
| `slug` | string | URL slug |
| `productUrl` | string | Public product page on the store's own site |
| `posProductId` | string | Id in the store's POS (e.g. Cova/IQMetrix GUID) |
| `venue` / `organization` | string | Owning venue / org ids |

### Naming & classification
| Field | Type | Meaning |
|---|---|---|
| `name` | string | Display name |
| `description` / `seoDescription` | string (HTML) | Marketing copy (contains `<br>` etc.) |
| `brand` | string \| object \| null | Brand. **Polymorphic**: sometimes a plain string, sometimes a nested object `{id, name, description, logo, website}`, sometimes null. Normalize to `brand.name` when it's an object (the reference scraper does this). |
| `productCategoryName` | string | Category the row came from |
| `productCategory` | string | Category id |
| `subType` | string | e.g. `Edible`, `Flower`, `Pre-Roll` |
| `cannabisType` | enum | `SATIVA`, `INDICA`, `HYBRID`, `HYBRID_SATIVA`, `HYBRID_INDICA`, `NA` |
| `cannabisStrain` | string | Strain name |
| `cannabisComplianceType` | enum | `FLOWER`, `EDIBLES`, `CONCENTRATE`, … (regulatory class) |
| `tags` | string[] | Misc tags |

### Weight / size
`weight` (number), `weightUnit` (`GRAMS`/`MG`/…), `weightInGrams` (number), `weightFormatted` (string), `size`, `flowerEquivalentInGrams`.

> On these NY menus each weight tier (3.5g, 7g, …) is typically a **separate product row**, not a
> `variants[]` entry — `variants` was empty for every product sampled. The `variants[]` / `modifierGroups[]`
> arrays still exist in the schema for stores that use them, so handle them defensively.

### Pricing
| Field | Meaning |
|---|---|
| `price` | Menu price the customer sees |
| `priceWithDiscounts` | Final price after any active discount (use this for the "sale" price) |
| `priceGross` / `priceNet` | Tax-inclusive ("out-the-door") figures; usually ≥ `price` |
| `priceType` | `REGULAR`, etc. |
| `discountValue`, `discountValueFinal`, `discountAmountFinal`, `discountType`, `discountTypeFinal` | Discount math; `discountType` is `PERCENT`/`AMOUNT` |
| `discounts` | array of structured discount objects (often empty even when on special — trust the price fields) |

> A product is "on sale" when `priceWithDiscounts < price` (or `price < priceGross`). The `discounts[]`
> array is frequently empty even for specials, so derive sale state from the numeric price fields.

### Inventory
`quantity` (current on-hand), `quantityTotal`, `quantitySold`, `quantityThreshold`, `totalSold`,
`totalQuantitySold`, `enable` (bool, listed/active), `new` (bool), `featured` (bool),
`productOrderType` (`ORDERING_ALLOWED`, …).

### Lab results — `labs` object (nested)
THC/CBD and terpene potency live in `labs`. Each analyte has a value plus a `...ContentUnit` (usually `%`):

```
labs.thc, labs.thcMax, labs.thcContentUnit
labs.thcA, labs.thcAContentUnit
labs.cbd, labs.cbdMax, labs.cbdContentUnit
labs.cbdA, labs.cbdAContentUnit
labs.cbg, labs.cbgContentUnit
labs.cbn, labs.cbnContentUnit
labs.potency           # MILD / MODERATE / STRONG ...
labs.terpenes          # array
labs.limonene, labs.linalool, labs.betaMyrcene, ...   # individual terpenes + *ContentUnit
```

**Fallback:** when `labs` is sparse, the same values are duplicated as a **JSON string** inside
`posLastSyncData` under dotted keys (`"labs.thc"`, `"labs.cbd"`, …). `json.loads()` it and read those
as a backstop. (`labs.thcA` vs `labs.thca` casing differs between sources — check both.)

### Media
`image` (string URL), `images` (array of `{fileUrl, originalFileUrl, order}`),
`productCategoryIconImage`. Image host is `imgix.dispenseapp.com` (supports imgix resize params).

### Effects & misc
`effects` (string[]), `terpenes` (string[]), `effectOnset`, `effectDuration`, `reviewStats`
(`{total, averageRating, ...}`), `created`, `modified` (ISO timestamps),
plus per-POS blobs (`cova`, `fourleaf`, `flowhubMaui`, `posLastSyncData`) — keep raw if you want them.

A complete, empty, fillable schema is in **`aiq_product.schema.json`** (JSON Schema draft-07) and the
flattened/normalized output target is in **`aiq_product.template.json`**.

---

## 7. Reference scraper

`aiq_scraper.py` (in this bundle) implements the full flow: categories → paginated products → dedupe →
flatten → write `dispense_menus_<timestamp>.json`. Run:

```bash
pip install curl_cffi
python aiq_scraper.py
```

It is configured for the three venues above; add more by appending `{name, venue_id}` to `DISPENSARIES`.

---

## 8. Operational notes & etiquette

- **Rate limiting:** keep a small delay (~0.25s) between calls. We saw no hard rate limit, but Cloudflare
  will get suspicious with bursts. Reuse one session/connection.
- **Robustness:** wrap each category page in try/except and continue — one bad page shouldn't kill a run.
- **Freshness:** `quantity`/pricing change throughout the day. Re-scrape on whatever cadence you need;
  use `modified` to detect changes.
- **If it suddenly 403s:** (1) re-grab `api-key` from the live site, (2) confirm you're still impersonating
  a current Chrome, (3) check `x-pathname`/`Origin` are set. These three cover essentially every block.
- **Schema drift:** Dispense adds fields over time. Always retain the **full raw payload** (the reference
  scraper keeps it under `raw`) so new fields aren't lost before you map them.
- **Legal/ToS:** this is public menu data, but review Dispense's ToS and the dispensaries' terms, and keep
  request volume low and respectful.
```
