#!/usr/bin/env python3
"""
Dutchie embedded-menu scraper.

Scrapes product menus from Dutchie's public consumer GraphQL API
(https://dutchie.com/graphql), which powers every Dutchie "embedded menu"
storefront at dutchie.com/embedded-menu/{dispensary_id}.

Configured for the 29 Dutchie dispensaries in stores.json (same directory).
Each store is identified by its 24-char hex dispensary id (the id in the
embedded-menu URL). Swap/extend stores.json to scrape any other Dutchie store.

-------------------------------------------------------------------------------
IMPORTANT — read before running
-------------------------------------------------------------------------------
1. Dutchie sits behind Cloudflare and **hard-blocks datacenter IPs**. Even with
   a perfect Chrome TLS fingerprint you will get HTTP 403 / "Sorry, you have
   been blocked" from a cloud server. Run this from a residential/mobile IP, or
   set a residential proxy:
       export DUTCHIE_RESIDENTIAL_PROXY="http://user:pass@host:port"
   (https:// and socks5:// also work). curl_cffi's Chrome impersonation handles
   the TLS side; the proxy handles the IP-reputation side.

2. The consumer API uses Apollo **Automatic Persisted Queries (APQ)**. The
   client normally sends only a sha256 hash of the query; that hash rotates
   roughly every few days. This scraper:
       (a) tries to auto-discover the *current* FilteredProducts hash from the
           live menu bundle (best-effort), falling back to DEFAULT_HASH;
       (b) if the server replies "PersistedQueryNotFound", automatically
           re-sends a full GraphQL query built from CONFIRMED-valid fields.
   So it keeps working across hash rotations. See README / report for how to
   refresh DEFAULT_HASH manually if you ever need full field fidelity.

Usage:
    pip install -r requirements.txt
    python dutchie_scraper.py                  # all stores in stores.json
    python dutchie_scraper.py --stores 64d2683c75332e0009f274f1
    python dutchie_scraper.py --pricing rec --per-page 100 --validate
    python dutchie_scraper.py --proxy http://user:pass@host:port
    # -> dutchie_menus_<UTC timestamp>.json
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    sys.exit("ERROR: curl_cffi not installed. Run: pip install -r requirements.txt")

GRAPHQL_URL = "https://dutchie.com/graphql"
MENU_BASE = "https://dutchie.com/embedded-menu"
IMPERSONATE = "chrome124"

# Last-known FilteredProducts persisted-query hash. APQ hashes rotate every few
# days; the scraper auto-discovers the current one at runtime and only uses this
# as a fallback. To refresh manually: open an embedded menu in Chrome -> DevTools
# -> Network -> filter "FilteredProducts" -> Headers/Payload -> copy the
# extensions.persistedQuery.sha256Hash value here.
DEFAULT_HASH = "47dd2eaa74293c63bdf3c67e217bac8741947a0ddd7a145c910560c04da0ec78"

HERE = Path(__file__).resolve().parent
STORES_FILE = HERE / "stores.json"

# ---------------------------------------------------------------------------
# Fallback GraphQL document.
#
# Only used when the persisted-query hash is stale (server returns
# PersistedQueryNotFound). Restricted to fields that are *confirmed* to exist on
# the Dutchie product type so the ad-hoc query can't be rejected for selecting an
# unknown field. This yields core menu data (identity, category, strain, status,
# prices, image, brand, and per-variant option/inventory). For the full canonical
# product object, keep DEFAULT_HASH current so the persisted path is used.
# ---------------------------------------------------------------------------
FALLBACK_QUERY = """query FilteredProducts($productsFilter: _ProductsFilterInput, $page: Int, $perPage: Int) {
  filteredProducts(productsFilter: $productsFilter, page: $page, perPage: $perPage) {
    products {
      id
      Name
      cName
      type
      strainType
      Status
      Image
      Prices
      brand { id name }
      POSMetaData {
        canonicalBrandName
        canonicalCategoryName
        children {
          option
          quantity
          quantityAvailable
        }
      }
    }
    queryInfo { totalCount totalPages }
  }
}"""
FALLBACK_HASH = hashlib.sha256(FALLBACK_QUERY.encode("utf-8")).hexdigest()


def build_headers(store_id: str) -> dict:
    referer = f"{MENU_BASE}/{store_id}"
    return {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://dutchie.com",
        "Referer": referer,
        "apollographql-client-name": "Marketplace (production)",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    }


def make_session(proxy: str | None):
    session = cffi_requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session


def build_variables(store_id: str, pricing: str, page: int, per_page: int) -> dict:
    return {
        "includeEnterpriseSpecials": False,
        "includeCannabinoids": True,
        "productsFilter": {
            "dispensaryId": store_id,
            "pricingType": pricing,           # "rec" or "med"
            "Status": "Active",
            "strainTypes": [],
            "subcategories": [],
            "types": [],
            "useCache": False,
            "sortDirection": 1,
            "sortBy": None,
            "isDefaultSort": True,
            "bypassOnlineThresholds": False,
            "isKioskMenu": False,
            "removeProductsBelowOptionThresholds": True,
        },
        "page": page,
        "perPage": per_page,
    }


def discover_hash(session, store_id: str) -> str | None:
    """Best-effort: pull the current FilteredProducts APQ hash from menu JS."""
    try:
        html = session.get(f"{MENU_BASE}/{store_id}", headers=build_headers(store_id),
                           impersonate=IMPERSONATE, timeout=30).text
    except Exception:
        return None
    bundles = re.findall(r'https://[^"\']+?\.js', html)
    # Inline hash next to the operation name (covers SSR'd apollo manifests).
    m = re.search(r'FilteredProducts["\']?\s*[:,]?\s*["\']?([a-f0-9]{64})', html)
    if m:
        return m.group(1)
    for url in bundles[:25]:
        if not any(k in url for k in ("main", "vendor", "menu", "chunk", "app")):
            continue
        try:
            js = session.get(url, headers={"User-Agent": build_headers(store_id)["User-Agent"]},
                             impersonate=IMPERSONATE, timeout=30).text
        except Exception:
            continue
        m = re.search(r'FilteredProducts["\'][^}]{0,200}?([a-f0-9]{64})', js)
        if m:
            return m.group(1)
    return None


def graphql_filtered_products(session, store_id: str, pricing: str, page: int,
                              per_page: int, hash_hex: str) -> dict:
    """One FilteredProducts call. Tries APQ hash, falls back to full query."""
    variables = build_variables(store_id, pricing, page, per_page)
    headers = build_headers(store_id)

    # Attempt 1: persisted-query hash only (server supplies the selection set).
    body = {
        "operationName": "FilteredProducts",
        "variables": variables,
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": hash_hex}},
    }
    data = _post(session, headers, body)
    if not _is_persisted_miss(data):
        return _unwrap(data)

    # Attempt 2: full query built from confirmed fields (hash of THIS query).
    body = {
        "operationName": "FilteredProducts",
        "query": FALLBACK_QUERY,
        "variables": variables,
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": FALLBACK_HASH}},
    }
    data = _post(session, headers, body)
    return _unwrap(data)


def _post(session, headers, body) -> dict:
    resp = session.post(GRAPHQL_URL, headers=headers, json=body,
                        impersonate=IMPERSONATE, timeout=45)
    if resp.status_code == 403:
        raise RuntimeError(
            "HTTP 403 from Cloudflare. This IP is blocked — run from a residential "
            "IP or set DUTCHIE_RESIDENTIAL_PROXY / --proxy."
        )
    resp.raise_for_status()
    return resp.json()


def _is_persisted_miss(data: dict) -> bool:
    for err in (data.get("errors") or []):
        code = (err.get("extensions") or {}).get("code", "")
        msg = err.get("message", "")
        if code == "PERSISTED_QUERY_NOT_FOUND" or "PersistedQueryNotFound" in msg:
            return True
    return False


def _unwrap(data: dict) -> dict:
    errors = data.get("errors")
    if errors and not (data.get("data") or {}).get("filteredProducts"):
        raise RuntimeError(f"GraphQL errors: {json.dumps(errors)[:500]}")
    return (data.get("data") or {}).get("filteredProducts") or {}


def fetch_all_products(session, store_id: str, pricing: str, per_page: int,
                       delay: float, hash_hex: str, max_products: int = 0) -> list:
    """Page through FilteredProducts; de-dupe on product id across pages."""
    out, seen, page = [], set(), 0
    while True:
        time.sleep(delay)
        try:
            fp = graphql_filtered_products(session, store_id, pricing, page, per_page, hash_hex)
        except Exception as exc:
            print(f"      ! error on page {page}: {exc}")
            break
        batch = fp.get("products") or []
        added = 0
        for prod in batch:
            pid = prod.get("id") or prod.get("_id")
            if pid in seen:
                continue          # products recur across category/special buckets
            seen.add(pid)
            out.append(prod)
            added += 1
        total_pages = (fp.get("queryInfo") or {}).get("totalPages")
        print(f"      page {page}: {len(batch)} rows, +{added} new (total so far {len(out)})")
        if max_products and len(out) >= max_products:
            return out[:max_products]
        if not batch or len(batch) < per_page:
            break
        if total_pages is not None and page + 1 >= total_pages:
            break
        page += 1
    return out


# ---------------------------------------------------------------------------
# Normalization: one record per variant (size/weight option), matching
# dutchie_product.template.json. Raw product kept under "raw".
# ---------------------------------------------------------------------------
def _brand_name(prod: dict) -> str | None:
    b = prod.get("brand")
    if isinstance(b, dict):
        return b.get("name")
    if isinstance(b, str):
        return b
    pos = prod.get("POSMetaData") or {}
    return pos.get("canonicalBrandName") or prod.get("brandName")


def _category(prod: dict) -> str | None:
    pos = prod.get("POSMetaData") or {}
    return prod.get("type") or pos.get("canonicalCategoryName")


def _potency(prod: dict, *keys):
    for k in keys:
        v = prod.get(k)
        if v in (None, "", []):
            continue
        if isinstance(v, dict):
            rng = v.get("range") or v.get("formatted")
            unit = {"PERCENTAGE": "%", "MILLIGRAMS": "mg", "MILLIGRAM": "mg"}.get(
                v.get("unit"), v.get("unit") or v.get("symbol") or "")
            if isinstance(rng, list) and rng:
                val = rng[-1]
                return f"{val}{unit}" if unit else str(val)
            if rng:
                return f"{rng}{unit}" if unit else str(rng)
        else:
            return str(v)
    return None


def _variants(prod: dict) -> list:
    pos = prod.get("POSMetaData") or {}
    children = pos.get("children")
    if isinstance(children, list) and children:
        return children
    # Fallback: parallel Options/Prices arrays (older menu shape).
    options = prod.get("Options") or []
    prices = prod.get("Prices") or []
    rec = prod.get("recPrices") or prices
    rows = []
    for i, opt in enumerate(options):
        rows.append({
            "option": opt,
            "price": prices[i] if i < len(prices) else None,
            "recPrice": rec[i] if i < len(rec) else None,
        })
    return rows or [{"option": None, "price": (prices[0] if prices else None)}]


def _num_price(*vals):
    for v in vals:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            m = re.search(r"\d+(?:\.\d+)?", v)
            if m:
                return float(m.group(0))
    return None


def normalize(prod: dict, store: dict, scraped_at: str) -> list:
    base = {
        "schema_version": "1.0",
        "dispensary_name": store.get("name"),
        "dispensary_id": store.get("store_id"),
        "dispensary_url": store.get("menu_url"),
        "product_id": prod.get("id") or prod.get("_id"),
        "product_name": prod.get("Name") or prod.get("name"),
        "brand": _brand_name(prod),
        "category": _category(prod),
        "subcategory": prod.get("subcategory"),
        "strain_type": prod.get("strainType"),
        "thc_level": _potency(prod, "THC", "THCContent", "thc"),
        "cbd_level": _potency(prod, "CBD", "CBDContent", "cbd"),
        "description": prod.get("Description") or prod.get("description"),
        "image_url": prod.get("Image") or (prod.get("images") or [None])[0],
        "status": prod.get("Status"),
        "special": bool(prod.get("special")),
        "product_url": f"{store.get('menu_url')}/product/{prod.get('id') or prod.get('_id')}",
        "scraped_at": scraped_at,
        "raw": prod,
    }
    records = []
    for v in _variants(prod):
        rec = dict(base)
        price = _num_price(v.get("price"), v.get("recPrice"), v.get("standardPrice"))
        qty = v.get("quantityAvailable")
        if qty is None:
            qty = v.get("quantity")
        rec.update({
            "variant_option": v.get("option"),
            "numeric_price": price,
            "display_price": f"${price:.2f}" if price is not None else None,
            "quantity_available": qty,
            "in_stock": (qty is None) or (isinstance(qty, (int, float)) and qty > 0),
        })
        records.append(rec)
    return records


def scrape_store(session, store: dict, pricing: str, per_page: int, delay: float,
                 max_products: int, no_discover: bool) -> dict:
    sid, name = store["store_id"], store["name"]
    print(f"\n=== {name} ({sid}) ===")
    hash_hex = DEFAULT_HASH
    if not no_discover:
        found = discover_hash(session, sid)
        if found:
            hash_hex = found
            print(f"  discovered persisted hash: {hash_hex[:12]}...")
        else:
            print("  (could not auto-discover hash; using DEFAULT_HASH / full-query fallback)")
    raw_products = fetch_all_products(session, sid, pricing, per_page, delay, hash_hex, max_products)
    scraped_at = datetime.now(timezone.utc).isoformat()
    records = []
    for p in raw_products:
        records.extend(normalize(p, store, scraped_at))
    print(f"  TOTAL unique products: {len(raw_products)}  ->  {len(records)} variant records")
    return {"products_raw": raw_products, "records": records}


def validate_raw(raw_products_by_store: dict) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        print("  (jsonschema not installed; skipping --validate)")
        return
    schema = json.loads((HERE / "dutchie_product.schema.json").read_text())
    validator = Draft7Validator(schema)
    total = errs = 0
    for store_name, products in raw_products_by_store.items():
        for p in products:
            total += 1
            for _ in validator.iter_errors(p):
                errs += 1
                break
    print(f"\nSchema validation: {total - errs}/{total} raw products valid against "
          f"dutchie_product.schema.json ({errs} with errors).")


def main():
    ap = argparse.ArgumentParser(description="Scrape Dutchie embedded-menu product menus.")
    ap.add_argument("--stores", nargs="*", help="Store ids to scrape (default: all in stores.json)")
    ap.add_argument("--pricing", default="rec", choices=["rec", "med"])
    ap.add_argument("--per-page", type=int, default=100)
    ap.add_argument("--delay", type=float, default=0.5, help="Seconds between requests")
    ap.add_argument("--max-products", type=int, default=0, help="Cap per store (0 = all)")
    ap.add_argument("--proxy", default=os.environ.get("DUTCHIE_RESIDENTIAL_PROXY"),
                    help="Proxy URL (or set DUTCHIE_RESIDENTIAL_PROXY)")
    ap.add_argument("--no-discover", action="store_true", help="Skip live hash auto-discovery")
    ap.add_argument("--validate", action="store_true", help="Validate raw products against the schema")
    args = ap.parse_args()

    all_stores = json.loads(STORES_FILE.read_text())
    if args.stores:
        wanted = set(args.stores)
        stores = [s for s in all_stores if s["store_id"] in wanted]
        missing = wanted - {s["store_id"] for s in stores}
        if missing:
            print(f"WARNING: unknown store ids ignored: {', '.join(sorted(missing))}")
    else:
        stores = all_stores

    if not args.proxy:
        print("NOTE: no proxy set. Dutchie blocks datacenter IPs; if you get 403s, set "
              "DUTCHIE_RESIDENTIAL_PROXY or pass --proxy.\n")

    session = make_session(args.proxy)
    out_records, out_raw = {}, {}
    for store in stores:
        result = scrape_store(session, store, args.pricing, args.per_page,
                              args.delay, args.max_products, args.no_discover)
        out_records[store["name"]] = result["records"]
        out_raw[store["name"]] = result["products_raw"]

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"dutchie_menus_{ts}.json"
    Path(fname).write_text(json.dumps(out_records, indent=2, ensure_ascii=False, default=str))

    total_prod = sum(len(v) for v in out_raw.values())
    total_rec = sum(len(v) for v in out_records.values())
    print(f"\nDone. {total_prod} unique products / {total_rec} variant records -> {fname}")
    for name, recs in out_records.items():
        print(f"   {name}: {len(out_raw[name])} products, {len(recs)} records")

    if args.validate:
        validate_raw(out_raw)


if __name__ == "__main__":
    main()
