#!/usr/bin/env python3
"""
AIQ / Dispense cannabis menu scraper.

Scrapes product menus from the Dispense API (api.dispenseapp.com), which powers
every AIQ-platform dispensary storefront at menus.dispenseapp.com/{venue_id}/menu.

Verified 2026-06-23 against the three venues configured below. To scrape any other
Dispense store, append {"name": ..., "venue_id": ...}; the venue_id is the hex id
in the store's menu URL.

Why curl_cffi: both the CDN and the API sit behind Cloudflare and reject plain
requests/httpx/urllib clients regardless of headers. impersonate="chrome124"
replicates a real Chrome TLS/HTTP2 fingerprint and passes.

Usage:
    pip install curl_cffi
    python aiq_scraper.py
    # -> dispense_menus_<UTC timestamp>.json
"""

import json
import sys
import time
from datetime import datetime, timezone

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    sys.exit("ERROR: curl_cffi not installed. Run: pip install curl_cffi")

API_BASE = "https://api.dispenseapp.com"
MENU_BASE = "https://menus.dispenseapp.com"
# Public client key baked into the Dispense storefront JS (same for all stores).
# If you start getting 401/403, re-grab it from a menu site's network requests.
API_KEY = "49dac8e0-7743-11e9-8e3f-a5601eb2e936"

DISPENSARIES = [
    {"name": "82-J Cannabis Company (Rec)", "venue_id": "390243df4f0ee7fa"},
    {"name": "Innocence Cannabis (Rec)", "venue_id": "0d177a4c05c521ca"},
    {"name": "Mrs Green's Cannary (Rec)", "venue_id": "74422ea119bfc60b"},
]

PAGE_LIMIT = 200       # max reliable page size
REQUEST_DELAY = 0.25   # seconds between requests (be polite)
IMPERSONATE = "chrome124"


def build_headers(venue_id: str, pathname: str) -> dict:
    return {
        "api-key": API_KEY,
        "x-pathname": pathname,
        "x-url": f"{MENU_BASE}/{venue_id}/menu",
        "Origin": MENU_BASE,
        "Referer": f"{MENU_BASE}/",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    }


def api_get(session, url: str, venue_id: str, pathname: str, params: dict = None) -> dict:
    resp = session.get(
        url,
        headers=build_headers(venue_id, pathname),
        params=params,
        impersonate=IMPERSONATE,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_categories(session, venue_id: str) -> list:
    path = f"/v1/venues/{venue_id}/product-categories"
    data = api_get(session, API_BASE + path, venue_id, path, {"orderPickUpType": "IN_STORE"})
    return data.get("data", [])


def fetch_category_products(session, venue_id: str, category_id: str) -> list:
    path = f"/v1/venues/{venue_id}/product-categories/{category_id}/products"
    out, skip = [], 0
    while True:
        time.sleep(REQUEST_DELAY)
        try:
            data = api_get(session, API_BASE + path, venue_id, path,
                           {"orderPickUpType": "IN_STORE", "limit": PAGE_LIMIT, "skip": skip})
        except Exception as exc:
            print(f"      ! error at skip={skip}: {exc}")
            break
        batch = data.get("data", [])
        if not batch:
            break
        out.extend(batch)
        if len(batch) < PAGE_LIMIT:   # no total/hasMore field; short page = last page
            break
        skip += PAGE_LIMIT
    return out


def _pos_sync(product: dict) -> dict:
    raw = product.get("posLastSyncData")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def flatten(product: dict, venue_id: str, dispensary_name: str) -> dict:
    labs = product.get("labs") or {}
    pos = _pos_sync(product)

    def lab(*keys):
        for k in keys:
            v = labs.get(k)
            if v is not None:
                return v
        for k in keys:
            v = pos.get(f"labs.{k}") or pos.get(k)
            if v is not None:
                return v
        return None

    brand = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    images = [img.get("fileUrl") for img in (product.get("images") or []) if img.get("fileUrl")]
    review = product.get("reviewStats") or {}
    price = product.get("price")
    price_disc = product.get("priceWithDiscounts")
    on_sale = bool(price_disc is not None and price is not None and price_disc < price)

    return {
        "dispensary_name": dispensary_name,
        "venue_id": venue_id,
        "product_id": product.get("id") or product.get("_id"),
        "sku": product.get("sku"),
        "slug": product.get("slug"),
        "product_url": product.get("productUrl"),
        "pos_product_id": product.get("posProductId"),

        "name": product.get("name"),
        "description": product.get("description"),
        "brand": brand,
        "product_category": product.get("productCategoryName"),
        "sub_type": product.get("subType"),
        "cannabis_type": product.get("cannabisType"),
        "cannabis_strain": product.get("cannabisStrain"),
        "cannabis_compliance": product.get("cannabisComplianceType"),
        "tags": product.get("tags") or [],

        "weight": product.get("weight"),
        "weight_unit": product.get("weightUnit"),
        "weight_in_grams": product.get("weightInGrams"),
        "weight_formatted": product.get("weightFormatted"),
        "size": product.get("size"),

        "price": price,
        "price_with_discounts": price_disc,
        "price_gross": product.get("priceGross"),
        "price_net": product.get("priceNet"),
        "price_type": product.get("priceType"),
        "on_sale": on_sale,
        "discount_value_final": product.get("discountValueFinal"),
        "discount_amount_final": product.get("discountAmountFinal"),
        "discount_type": product.get("discountTypeFinal") or product.get("discountType"),

        "quantity": product.get("quantity"),
        "quantity_total": product.get("quantityTotal"),
        "quantity_sold": product.get("quantitySold"),
        "quantity_threshold": product.get("quantityThreshold"),
        "enable": product.get("enable"),
        "new": product.get("new"),
        "featured": product.get("featured"),

        "thc": lab("thc"),
        "thc_unit": labs.get("thcContentUnit"),
        "thca": lab("thcA", "thca"),
        "cbd": lab("cbd"),
        "cbd_unit": labs.get("cbdContentUnit"),
        "cbda": lab("cbdA", "cbda"),
        "cbg": lab("cbg"),
        "cbn": lab("cbn"),
        "potency": labs.get("potency"),

        "effects": product.get("effects") or [],
        "terpenes": product.get("terpenes") or [],
        "effect_onset": product.get("effectOnset"),
        "effect_duration": product.get("effectDuration"),

        "image": product.get("image"),
        "images": images,

        "review_total": review.get("total"),
        "review_average_rating": review.get("averageRating"),

        "created": product.get("created"),
        "modified": product.get("modified"),
        "scraped_at": datetime.now(timezone.utc).isoformat(),

        "raw": product,
    }


def scrape_dispensary(session, dispensary: dict) -> list:
    venue_id, name = dispensary["venue_id"], dispensary["name"]
    print(f"\n=== {name} ({venue_id}) ===")
    categories = fetch_categories(session, venue_id)
    print(f"  {len(categories)} categories")

    products, seen = [], set()
    for cat in categories:
        cid = cat.get("id") or cat.get("_id")
        cname = cat.get("name", "?")
        rows = fetch_category_products(session, venue_id, cid)
        added = 0
        for raw in rows:
            pid = raw.get("id") or raw.get("_id")
            if pid in seen:
                continue   # de-dupe (Specials/Offers re-list products)
            seen.add(pid)
            products.append(flatten(raw, venue_id, name))
            added += 1
        print(f"    {cname}: {len(rows)} rows, +{added} new")
    print(f"  TOTAL unique: {len(products)}")
    return products


def main():
    session = cffi_requests.Session()
    output = {d["name"]: scrape_dispensary(session, d) for d in DISPENSARIES}

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"dispense_menus_{ts}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    total = sum(len(v) for v in output.values())
    print(f"\nDone. {total} products -> {fname}")
    for name, prods in output.items():
        print(f"   {name}: {len(prods)}")


if __name__ == "__main__":
    main()
