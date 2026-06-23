# Scraping Dutchie Dispensary Menus — Developer Report

**Scope:** The 29 Dutchie dispensaries in the master list (all on `dutchie.com/embedded-menu/...`).
**Status:** Built from Dutchie's documented/observed consumer GraphQL contract. **Not** live-validated
from this environment — Dutchie's Cloudflare layer hard-blocks datacenter IPs (see §9). Run the bundled
`dutchie_scraper.py` from a residential/mobile IP (or a residential proxy) to pull real data.

---

## 1. TL;DR

Dutchie embedded menus are served by a single **public consumer GraphQL API** at
**`https://dutchie.com/graphql`**. The storefront at `dutchie.com/embedded-menu/{dispensaryId}` is a
React app that calls this API. There is **no login and no per-store secret** — a store is addressed
purely by its **24-char hex `dispensaryId`** (the id in the embedded-menu URL). What you actually need:

1. The **`dispensaryId`** for each store (already extracted into `stores.json`).
2. The **`FilteredProducts`** GraphQL operation, sent either as an **Apollo persisted query** (a sha256
   hash — what the real client sends) or as a full query document.
3. A **real-Chrome TLS fingerprint** and a **residential IP**. Dutchie is behind Cloudflare; datacenter
   IPs and non-browser TLS stacks are blocked. Use **`curl_cffi` with `impersonate="chrome124"`** plus a
   residential exit. This is the single most important detail — it's *more* aggressive than AIQ/Dispense.

Flow: for each store, call `FilteredProducts` with `page`/`perPage` → page until short page → **de-dupe on
product `id`** → **expand each product into one record per variant** (weight/size) using
`POSMetaData.children[]`.

### The 29 stores

All ids live in `stores.json`. A few examples:

| Dispensary | `dispensaryId` | Embedded menu |
|---|---|---|
| Canterra | `64d2683c75332e0009f274f1` | https://dutchie.com/embedded-menu/64d2683c75332e0009f274f1 |
| Public Flower | `6569f41c44db8e0009709faf` | https://dutchie.com/embedded-menu/6569f41c44db8e0009709faf |
| Mammoth Cannabis | `6674575e7531e65c8d1c3f4a` | https://dutchie.com/embedded-menu/6674575e7531e65c8d1c3f4a |
| Star Buds | `6595855102771e0009439283` | https://dutchie.com/embedded-menu/6595855102771e0009439283 |
| Happy Times (Buffalo) | `67196f2c8c7ea2c66ca086b5` | https://dutchie.com/embedded-menu/67196f2c8c7ea2c66ca086b5 |

> The same scraper works for **any** Dutchie store — just add `{name, store_id, menu_url}` to
> `stores.json`. You can read a store's `dispensaryId` straight out of its embedded-menu URL, or from
> DevTools → Network → any `FilteredProducts` request → Payload → `productsFilter.dispensaryId`.

---

## 2. Endpoint & operation

| | |
|---|---|
| Endpoint | `POST https://dutchie.com/graphql` (the client also issues `GET /graphql?...` for persisted queries) |
| Operation | `FilteredProducts` |
| Response path | `data.filteredProducts.products[]` (array of product objects) |
| Paging info | `data.filteredProducts.queryInfo.{totalCount,totalPages}` when present |

Other operations the storefront uses (not required for a product scrape, but handy):
`MenuFilters` (category/brand facets), `GetMenuSelection`, `ConsumerDispensaries`/`DispensaryByCName`
(store metadata). For a menu/price/inventory scrape, **`FilteredProducts` is the only one you need**.

### Variables

```jsonc
{
  "includeEnterpriseSpecials": false,
  "includeCannabinoids": true,
  "productsFilter": {
    "dispensaryId": "64d2683c75332e0009f274f1",  // the store
    "pricingType": "rec",                          // "rec" or "med"
    "Status": "Active",
    "types": [],                                   // [] = all categories; or ["Flower"], ["Pre-Rolls"], ...
    "strainTypes": [],
    "subcategories": [],
    "useCache": false,
    "sortDirection": 1,
    "sortBy": null,
    "isDefaultSort": true,
    "bypassOnlineThresholds": false,
    "isKioskMenu": false,
    "removeProductsBelowOptionThresholds": true
  },
  "page": 0,
  "perPage": 100
}
```

- Leave `types: []` to fetch the **whole menu** in one paged sweep (simplest; then de-dupe). Or iterate
  per category (`["Flower"]`, `["Pre-Rolls"]`, `["Vaporizers"]`, `["Edible"]`, `["Concentrate"]`,
  `["Tincture"]`, `["Topicals"]`, `["Accessories"]`, …) if you want each product's "home" category.
- `pricingType` is `"rec"` for adult-use (all NY stores here) or `"med"` for medical.
- `bypassOnlineThresholds`/`removeProductsBelowOptionThresholds` control whether low-stock SKUs are
  hidden. Defaults above mirror the live storefront.

---

## 3. Authentication & the Cloudflare problem (the part that matters)

There is **no OAuth, no bearer token, no API key.** Access is gated by **Cloudflare bot management**, which
is stricter than AIQ/Dispense:

- **TLS/JA3 fingerprint is enforced.** Plain `requests`/`httpx`/`urllib` are blocked even with perfect
  headers. Use **`curl_cffi` `impersonate="chrome124"`** (or a real browser / Playwright).
- **IP reputation is enforced.** Datacenter/cloud IPs get `HTTP 403` + an "Sorry, you have been blocked"
  interstitial regardless of TLS. **You must exit from a residential or mobile IP.** Every public Dutchie
  scraper relies on this. Set one via:
  ```bash
  export DUTCHIE_RESIDENTIAL_PROXY="http://user:pass@host:port"   # https:// or socks5:// also fine
  ```
  Providers that work: Bright Data, Oxylabs, Decodo/Smartproxy, IPRoyal — pick a **residential** endpoint.
  If you run the scraper on your own home machine, no proxy is needed.

Headers the scraper sends on every call:

```
Content-Type:                application/json
Origin:                      https://dutchie.com
Referer:                     https://dutchie.com/embedded-menu/{dispensaryId}
Accept:                      application/json
Accept-Language:             en-US,en;q=0.9
apollographql-client-name:   Marketplace (production)
User-Agent:                  Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36
```

---

## 4. Persisted queries (APQ) — important, and how the scraper stays robust

Dutchie uses Apollo **Automatic Persisted Queries**. The real client normally does **not** send the query
text — it sends only:

```jsonc
"extensions": { "persistedQuery": { "version": 1, "sha256Hash": "<64-hex>" } }
```

…and the server looks up the registered query by hash. **The hash for `FilteredProducts` rotates** (it
changes whenever Dutchie ships a new menu bundle, roughly every few days). A hardcoded hash will
eventually return `PersistedQueryNotFound`.

`dutchie_scraper.py` handles this with a three-layer strategy so it keeps working:

1. **Auto-discover the current hash** at runtime from the live menu JS bundle (`discover_hash()`), since
   the scraper runs on your (allowed) residential IP and can load the storefront.
2. If discovery fails, fall back to **`DEFAULT_HASH`** (a last-known value at the top of the file).
3. If the server replies `PersistedQueryNotFound`, **automatically re-send a full GraphQL query** built
   only from **confirmed-valid fields** (`FALLBACK_QUERY`), with that query's own sha256 as the APQ hash
   (the standard APQ "register" handshake). This guarantees you still get core data even with a stale hash.

**To refresh `DEFAULT_HASH` manually** (gives the full canonical product object on the fast path): open any
store's embedded menu in Chrome → DevTools → Network → filter `FilteredProducts` → look at
**Payload** (or the `extensions` query param) → copy `persistedQuery.sha256Hash` → paste into
`DEFAULT_HASH`. Do the same for the variables if Dutchie ever changes the filter shape.

---

## 5. Pagination

`FilteredProducts` is offset-paged via `page` (0-based) + `perPage`:

```
page = 0
loop:
    FilteredProducts(productsFilter={...}, page=page, perPage=100)
    products = data.filteredProducts.products
    keep products (de-duped on id)
    if products is empty or len(products) < perPage: stop      # last page
    if queryInfo.totalPages present and page+1 >= totalPages: stop
    page += 1
```

`perPage=100` is safe. `queryInfo.totalPages`/`totalCount` are returned on the persisted-query path and
let you stop precisely; the "short page" check is the reliable fallback when they're absent.

---

## 6. De-duplication (important)

A product can surface under multiple buckets — its real category, the **specials/featured** lists, and
(if `includeEnterpriseSpecials`) chain-wide promos. When you sweep with `types: []` you mostly avoid this,
but specials still overlap. **De-dupe on the product `id`** as you ingest (the scraper keeps a `seen` set).
`id` is a stable 24-char hex string and is the canonical key.

> If you instead iterate per category, the same product *will* repeat across the category list and the
> specials list — de-duping on `id` is mandatory there.

---

## 7. The product object & variants (the schema)

Each `products[]` entry is one product; **purchasable weights/sizes are nested**, not separate rows
(the opposite of AIQ/Dispense). The load-bearing fields:

### Identity & classification
| Field | Type | Meaning |
|---|---|---|
| `id` | string | Stable product id (24-hex). **De-dupe key.** |
| `cName` | string | URL slug |
| `Name` | string | Display name (capital `N`) |
| `Description` | string (HTML) | Marketing copy |
| `brand` | string \| object \| null | **Polymorphic** — object `{id,name}`, plain string, or null. Fallback: `POSMetaData.canonicalBrandName`. |
| `type` | string | Category: `Flower`, `Pre-Rolls`, `Vaporizers`, `Edible`, `Concentrate`, `Tincture`, `Topicals`, `Accessories`, … |
| `subcategory` | string | e.g. `disposables`, `pre-ground`, `gummies` |
| `strainType` | string | `Indica`/`Sativa`/`Hybrid`/`Indica-Hybrid`/`Sativa-Hybrid`/… |
| `Status` | string | `Active`, … |

### Potency
`THC` / `CBD` are usually objects `{ range: [min, max], unit }` (`unit` ∈ `PERCENTAGE`, `MILLIGRAMS`), but
can be a bare number/string on some stores. `cannabinoidsV2[]` carries a fuller breakdown when
`includeCannabinoids=true`. The scraper's `_potency()` helper normalizes all of these to a display string.

### Pricing & variants — `POSMetaData.children[]`
This is the heart of a Dutchie menu. `POSMetaData.children` is an array with **one entry per variant**
(per weight/size SKU):

```
POSMetaData.children[].option              # "1g", "3.5g", "7g", "20 Pack", ...
POSMetaData.children[].price / .recPrice / .standardPrice / .kioskPrice
POSMetaData.children[].quantity            # on-hand
POSMetaData.children[].quantityAvailable   # live sellable units  <-- real-time stock
```

Older/alternate menu shapes expose the same data as **parallel arrays** instead:
`Options[]` (labels) index-aligned with `Prices[]` / `recPrices[]` / `recSpecialPrices[]`. The scraper's
`_variants()` prefers `POSMetaData.children` and falls back to the parallel arrays.

> **Per-variant output:** because pricing/stock is per weight, the normalized output (and
> `dutchie_product.template.json`) emits **one record per variant** — a product with `1g/3.5g/7g`
> produces three records sharing the same `product_id`. The pair `(product_id, variant_option)` is unique.

### Specials
`special` (bool) flags an active deal; `recSpecialPrices[]` / `specialData` carry the discounted figures.
Treat a SKU as "on sale" when a special price is present and below the regular price.

### Media
`Image` (primary URL on `images.dutchie.com`), `images[]`. The host supports resize query params.

A complete, empty, fillable schema for the **raw** product is in **`dutchie_product.schema.json`**
(JSON Schema draft-07, `additionalProperties: true` because the persisted-query path returns Dutchie's
full canonical object with many more, store-dependent fields). The flattened/normalized output target is
**`dutchie_product.template.json`**, and **`sample_raw_product.json`** shows the field shapes.

---

## 8. Reference scraper

`dutchie_scraper.py` implements the full flow: per store → (discover hash) → paged `FilteredProducts` →
de-dupe on `id` → expand variants → normalize → write `dutchie_menus_<UTC timestamp>.json`.

```bash
pip install -r requirements.txt

# all 29 stores (run from a residential IP, or set a proxy):
export DUTCHIE_RESIDENTIAL_PROXY="http://user:pass@host:port"   # omit if on a home connection
python dutchie_scraper.py

# smoke test one store + validate the raw payloads against the schema:
python dutchie_scraper.py --stores 64d2683c75332e0009f274f1 --max-products 10 --validate
```

Useful flags: `--pricing {rec,med}`, `--per-page`, `--delay`, `--max-products`, `--proxy`,
`--no-discover`, `--validate`. Output is keyed by store name; each value is a list of normalized
per-variant records (see template), each retaining the full raw product under `raw`.

---

## 9. Why this wasn't live-validated here (and how to validate)

From this build environment (a datacenter VM), **every** request to `dutchie.com` / `dutchie.com/graphql`
returns `HTTP 403` "Sorry, you have been blocked" — Cloudflare blocks the IP range outright, even with
Chrome TLS impersonation. This is expected and is exactly why the scraper requires a residential exit.
Validate on your end in one command from a residential connection:

```bash
python dutchie_scraper.py --stores 64d2683c75332e0009f274f1 --max-products 25 --validate
# -> prints "N/N raw products valid against dutchie_product.schema.json (0 with errors)"
```

If you get a `403`: confirm you're on a residential IP / proxy and still impersonating a current Chrome.
If you get `PersistedQueryNotFound` repeatedly: the auto-discovery + full-query fallback should cover it,
but you can refresh `DEFAULT_HASH` (see §4) for full field fidelity.

---

## 10. Operational notes & etiquette

- **Rate limiting:** keep a small delay (default `0.5s`) between requests and reuse one session. Bursts
  from a single IP draw Cloudflare scrutiny faster than AIQ did.
- **Robustness:** each page is wrapped in try/except and the run continues on error — one bad page won't
  kill a store.
- **Freshness:** `quantityAvailable` and special pricing change throughout the day. Re-scrape on whatever
  cadence you need.
- **Schema drift:** the persisted-query path returns Dutchie's full canonical object, which grows over
  time. The scraper retains the **full raw payload** under `raw` so new fields are never lost before you
  map them; `additionalProperties: true` keeps the schema from rejecting them.
- **Legal/ToS:** this is public menu data, but review Dutchie's ToS and each dispensary's terms, and keep
  request volume low and respectful.
```

