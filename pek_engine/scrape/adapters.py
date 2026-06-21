"""Per-platform menu adapters.

Each adapter has the signature ``fetch(entry, client, batch_id) -> list[dict]``
and returns rows in the canonical raw-listing schema (see PRD 4.3), which is the
exact shape the normalization engine ingests. Endpoints mirror the proven
harvesting script; all network I/O goes through the injected ``client`` so the
parsing is unit-testable offline with a ``FixtureClient``.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Callable

from .registry import DispensaryEntry


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _s(value) -> str:
    return "" if value is None else str(value).strip()


def _first(d: dict, *keys, default=""):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def listing(entry: DispensaryEntry, batch_id: str, *, product_id, title,
            brand="", category="", subcategory="", strain_type="", thc="",
            thc_unit="", cbd="", cbd_unit="", weight="", price="", image="",
            product_url="", raw=None) -> dict:
    """Build one canonical raw-listing row."""
    if isinstance(brand, dict):
        brand = _first(brand, "name", "brandName", default="")
    return {
        "dispensary": entry.name,
        "dispensary_id": entry.external_id,
        "product_id": _s(product_id),
        "title": _s(title),
        "brand": _s(brand),
        "category": _s(category),
        "original_type": _s(category),
        "original_subcategory": _s(subcategory),
        "strain_type": _s(strain_type),
        "thc": _s(thc),
        "thc_unit": _s(thc_unit),
        "cbd": _s(cbd),
        "cbd_unit": _s(cbd_unit),
        "weight": _s(weight),
        "price": _s(price),
        "image": _s(image),
        "product_url": _s(product_url),
        "platform": entry.raw_platform,
        "scraped_at": _now(),
        "batch_id": batch_id,
        "raw_data": raw if raw is not None else {},
    }


# --------------------------------------------------------------------------
# Dutchie (GraphQL persisted query, GET, warmed Cloudflare session)
# --------------------------------------------------------------------------
_DUTCHIE_URL = "https://dutchie.com/graphql"
_DUTCHIE_HASH_FILTERED = "98b4aaef79a84ae804b64d550f98dd64d7ba0aa6d836eb6b5d4b2ae815c95e32"
_DUTCHIE_HEADERS = {
    "accept": "application/json", "apollo-require-preflight": "true",
    "content-type": "application/json", "origin": "https://dutchie.com",
    "referer": "https://dutchie.com/",
}


def _dutchie_get(client, variables: dict) -> dict:
    params = {
        "operationName": "FilteredProducts",
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps(
            {"persistedQuery": {"version": 1, "sha256Hash": _DUTCHIE_HASH_FILTERED}},
            separators=(",", ":")),
    }
    return client.get_json(_DUTCHIE_URL, params=params, headers=_DUTCHIE_HEADERS)


def fetch_dutchie(entry: DispensaryEntry, client, batch_id: str,
                  pricing_type: str = "rec") -> list[dict]:
    client.warm("https://dutchie.com/")
    out: list[dict] = []
    page, total_pages = 0, None
    while True:
        variables = {
            "includeEnterpriseSpecials": False,
            "productsFilter": {
                "dispensaryId": entry.external_id, "pricingType": pricing_type,
                "strainTypes": [], "subcategories": [], "Status": "Active",
                "types": [], "useCache": True, "isDefaultSort": True,
                "sortBy": "popularSortIdx", "sortDirection": 1,
                "bypassOnlineThresholds": False, "isKioskMenu": False,
                "removeProductsBelowOptionThresholds": True,
                "platformType": "ONLINE_MENU", "preOrderType": None,
            },
            "page": page, "perPage": 100,
        }
        data = _dutchie_get(client, variables)
        fp = (data.get("data") or {}).get("filteredProducts") or {}
        products = fp.get("products") or []
        for p in products:
            out.append(_map_dutchie(p, entry, batch_id, pricing_type))
        if total_pages is None:
            total_pages = (fp.get("queryInfo") or {}).get("totalPages", 1)
        page += 1
        if not products or page >= total_pages:
            break
    return out


def _map_dutchie(p: dict, entry: DispensaryEntry, batch_id: str,
                 pricing_type: str = "rec") -> dict:
    options = p.get("Options") or []
    rec_prices = p.get("recPrices") or []
    med_prices = p.get("medicalPrices") or []
    prices = med_prices if pricing_type == "med" else rec_prices
    thc = p.get("THCContent") or {}
    thc_range = thc.get("range") or [] if isinstance(thc, dict) else []
    pid = _s(_first(p, "_id", "id"))
    menu = entry.menu_url.rstrip("/")
    return listing(
        entry, batch_id, product_id=pid,
        title=p.get("Name"),
        brand=_first(p, "brandName", "brand", default=""),
        category=p.get("type"),
        subcategory=p.get("subcategory"),
        strain_type=p.get("strainType"),
        thc=_s(thc_range[0]) if thc_range else "",
        thc_unit=_s(thc.get("unit")) if isinstance(thc, dict) else "",
        weight=_s(options[0]) if options else "",
        price=_s(prices[0]) if prices else "",
        image=_s(p.get("Image")),
        product_url=f"{menu}/products/{pid}" if menu and pid else "",
        raw=p,
    )


# --------------------------------------------------------------------------
# Carrot (Typesense) — external_id format: host|api_key|index
# --------------------------------------------------------------------------
def fetch_carrot(entry: DispensaryEntry, client, batch_id: str) -> list[dict]:
    try:
        host, key, index = entry.external_id.split("|")
    except ValueError:
        raise ValueError("Carrot external_id must be 'host|api_key|index'")
    url = f"https://{host}/collections/{index}/documents/search"
    headers = {"X-TYPESENSE-API-KEY": key}
    out: list[dict] = []
    page = 1
    while True:
        params = {"q": "*", "per_page": 250, "page": page}
        data = client.get_json(url, params=params, headers=headers)
        hits = data.get("hits") or []
        if not hits:
            break
        for hit in hits:
            doc = hit.get("document") or {}
            out.append(listing(
                entry, batch_id,
                product_id=_first(doc, "id", "productId", "slug"),
                title=doc.get("name"),
                brand=_first(doc, "brand", "brandName", default=""),
                category=_first(doc, "category", "productType"),
                subcategory=_first(doc, "subcategory", "strainType"),
                strain_type=doc.get("strainType"),
                thc=_s(doc.get("thc") or doc.get("thcContent")),
                weight=_s(doc.get("weight") or doc.get("size")),
                price=_s(_first(doc, "price", "discountedPrice", default="")),
                image=_first(doc, "image", "imageUrl", default=""),
                product_url=_s(doc.get("url") or entry.menu_url),
                raw=doc,
            ))
        page += 1
    return out


# --------------------------------------------------------------------------
# iHeartJane (Algolia)
# --------------------------------------------------------------------------
def fetch_jane(entry: DispensaryEntry, client, batch_id: str) -> list[dict]:
    app_id, api_key = "VF4RX0N23A", "edc5435c65d771cecbd98bbd488aa8d3"
    url = ("https://search.iheartjane.com/1/indexes/menu-products-production/query"
           "?x-algolia-agent=Algolia%20for%20JavaScript")
    headers = {"X-Algolia-Application-Id": app_id, "X-Algolia-API-Key": api_key,
               "Content-Type": "application/json"}
    out: list[dict] = []
    page, total_pages = 0, 1
    while page < total_pages:
        payload = {"query": "", "filters": f"store_id:{entry.external_id}",
                   "hitsPerPage": 100, "page": page}
        data = client.post_json(url, json_body=payload, headers=headers)
        hits = data.get("hits") or []
        if not hits:
            break
        for h in hits:
            out.append(listing(
                entry, batch_id,
                product_id=_first(h, "product_id", "objectID"),
                title=h.get("name"),
                brand=_s(h.get("brand")),
                category=_first(h, "kind", "category"),
                subcategory=_first(h, "kind_subtype", "category_subtype"),
                strain_type=_s(h.get("category")),
                thc=_s(h.get("percent_thc")), thc_unit="PERCENTAGE",
                cbd=_s(h.get("percent_cbd")), cbd_unit="PERCENTAGE",
                price=_s(_first(h, "sort_price", "price", default="")),
                image=_s(h.get("photos") or h.get("image_urls")),
                product_url=_s(entry.menu_url),
                raw=h,
            ))
        total_pages = data.get("nbPages", 1)
        page += 1
    return out


# --------------------------------------------------------------------------
# Blaze
# --------------------------------------------------------------------------
def fetch_blaze(entry: DispensaryEntry, client, batch_id: str) -> list[dict]:
    url = "https://ecom-api.blaze.me/api/v1/products/"
    origin = entry.website or "https://blaze.me"
    headers = {"Accept": "application/vnd.api+json", "Origin": origin,
               "X-Store": entry.external_id, "X-App-Mode": "default"}
    out: list[dict] = []
    offset, limit = 0, 100
    while True:
        params = {"limit": limit, "offset": offset, "delivery_type": "pickup"}
        data = client.get_json(url, params=params, headers=headers)
        items = data.get("data") or []
        if not items:
            break
        for it in items:
            attr = it.get("attributes") or {}
            up = attr.get("unit_price")
            price = (up.get("amount", 0) / 100) if isinstance(up, dict) else ""
            out.append(listing(
                entry, batch_id, product_id=it.get("id"),
                title=attr.get("name"),
                brand=_first(attr, "brand", "brand_name", default=""),
                category=_first(attr, "type", "category"),
                strain_type=_s(attr.get("classification")),
                weight=_s(attr.get("size")), price=_s(price),
                image=_s(attr.get("image_url")),
                product_url=_s(entry.menu_url), raw=it,
            ))
        offset += len(items)
        if offset >= (data.get("meta") or {}).get("total_count", 0):
            break
    return out


# --------------------------------------------------------------------------
# Weedmaps
# --------------------------------------------------------------------------
def fetch_weedmaps(entry: DispensaryEntry, client, batch_id: str) -> list[dict]:
    slug = entry.external_id
    base = (f"https://api-g.weedmaps.com/discovery/v1/listings/dispensaries/"
            f"{slug}/menu_items")
    origin = entry.menu_url or f"https://{slug}.wm.store"
    headers = {"Origin": origin, "Referer": origin.rstrip("/") + "/"}
    out: list[dict] = []
    page, total, page_size = 1, None, 100
    while True:
        params = {"include[]": "facets.categories", "page": page,
                  "page_size": page_size}
        data = client.get_json(base, params=params, headers=headers)
        items = ((data.get("data") or {}).get("menu_items")) or []
        for it in items:
            out.append(_map_weedmaps(it, entry, batch_id))
        if total is None:
            total = ((data.get("meta") or {}).get("total_menu_items")) or len(items)
        page += 1
        if not items or len(out) >= total:
            break
    return out


def _map_weedmaps(it: dict, entry: DispensaryEntry, batch_id: str) -> dict:
    be = it.get("brand_endorsement") or {}
    cat = it.get("category") or {}
    edge = it.get("edge_category") or {}
    avatar = it.get("avatar_image") or {}
    genetics = it.get("genetics_tag") or {}
    price = it.get("price")
    if isinstance(price, dict):
        price = price.get("price")
    if price in (None, ""):
        plist = it.get("prices") or []
        if plist and isinstance(plist[0], dict):
            price = plist[0].get("price")
    return listing(
        entry, batch_id, product_id=it.get("id"), title=it.get("name"),
        brand=be.get("brand_name", "") if isinstance(be, dict) else "",
        category=cat.get("name", "") if isinstance(cat, dict) else "",
        subcategory=edge.get("name", "") if isinstance(edge, dict) else "",
        strain_type=genetics.get("name", "") if isinstance(genetics, dict) else "",
        price=_s(price),
        image=avatar.get("original_url", "") if isinstance(avatar, dict) else "",
        product_url=_s(entry.menu_url), raw=it,
    )


# --------------------------------------------------------------------------
# Dispense / AIQ
# --------------------------------------------------------------------------
def fetch_dispense(entry: DispensaryEntry, client, batch_id: str) -> list[dict]:
    venue_id = entry.external_id
    headers = {"Accept": "application/json", "x-dispense-tenant-id": venue_id}
    cat_url = f"https://api.dispenseapp.com/v1/venues/{venue_id}/product-categories"
    cats = (client.get_json(cat_url, params={"orderPickUpType": "IN_STORE"},
                            headers=headers).get("data")) or []
    out: list[dict] = []
    for cat in [c for c in cats if c.get("type") == "SYSTEM"]:
        cat_id = cat.get("_id")
        skip, limit = 0, 200
        while True:
            url = (f"https://api.dispenseapp.com/v1/venues/{venue_id}/"
                   f"product-categories/{cat_id}/products")
            data = client.get_json(url, params={"skip": skip, "limit": limit,
                                                 "orderPickUpType": "IN_STORE"},
                                   headers={**headers, "x-pathname": url})
            batch = data.get("data") or []
            if not batch:
                break
            for it in batch:
                out.append(listing(
                    entry, batch_id, product_id=_first(it, "_id", "id"),
                    title=it.get("name"),
                    brand=_first(it, "brand", "brandName", default=""),
                    category=cat.get("name", ""),
                    strain_type=_s(it.get("cannabisType")),
                    weight=_s(it.get("weight")),
                    price=_s(it.get("price")),
                    image=_s(it.get("image")),
                    product_url=_s(entry.menu_url), raw=it,
                ))
            if len(batch) < limit:
                break
            skip += limit
    return out


# --------------------------------------------------------------------------
# Flowhub (proxy API)
# --------------------------------------------------------------------------
def fetch_flowhub(entry: DispensaryEntry, client, batch_id: str) -> list[dict]:
    url = ("https://dispensary-api-ac9613fa4c11.herokuapp.com/api/flowhub/"
           f"inventoryByLocation?location_id={entry.external_id}&toggleVape=false")
    headers = {"Accept": "application/json", "Origin": entry.website or "",
               "Referer": entry.website or ""}
    data = client.get_json(url, headers=headers)
    items = data if isinstance(data, list) else (data.get("products") or [])
    out: list[dict] = []
    for it in items:
        out.append(listing(
            entry, batch_id, product_id=it.get("id"), title=it.get("name"),
            brand=_first(it, "brand", "brandName", default=""),
            category=_first(it, "category", "type"),
            weight=_s(it.get("size")), price=_s(it.get("price")),
            image=_s(it.get("image")), product_url=_s(entry.menu_url), raw=it,
        ))
    return out


ADAPTERS: dict[str, Callable[..., list[dict]]] = {
    "dutchie": fetch_dutchie,
    "carrot": fetch_carrot,
    "jane": fetch_jane,
    "blaze": fetch_blaze,
    "weedmaps": fetch_weedmaps,
    "dispense": fetch_dispense,
    "flowhub": fetch_flowhub,
}

# Platforms recognized but needing a browser-HTML scraper (not pure JSON API).
# Stubs raise a clear message; implemented behind the same interface later.
HTML_PLATFORMS = {"proteus", "kushmart", "treez"}
