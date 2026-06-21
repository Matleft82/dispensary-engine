"""Scraper adapter + runner tests (offline, fixture-driven)."""

from __future__ import annotations

from pek_engine.scrape import adapters
from pek_engine.scrape.http import FixtureClient
from pek_engine.scrape.registry import DispensaryEntry, PLATFORM_ALIASES, load_registry
from pek_engine.scrape.runner import harvest


def _entry(platform="dutchie", ext="64d2", raw="Dutchie",
           menu="https://dutchie.com/embedded-menu/64d2"):
    return DispensaryEntry(name="Test Shop", platform=platform, raw_platform=raw,
                           external_id=ext, menu_url=menu, website="https://x.co")


def test_dutchie_adapter_maps_canonical_schema():
    pages = [{
        "__paged__": True,
        "data": {"filteredProducts": {"products": [{
            "_id": "abc", "Name": "Blue Dream | Live Resin | Aio | 1g",
            "brandName": "Stiiizy", "type": "Vaporizers", "subcategory": "Cart",
            "strainType": "Hybrid", "THCContent": {"range": [85], "unit": "PERCENTAGE"},
            "Options": ["1g"], "recPrices": [45], "Image": "http://img/x"}],
            "queryInfo": {"totalPages": 1}}},
    }]
    rows = adapters.fetch_dutchie(_entry(), FixtureClient({"graphql": pages}), "b1")
    assert len(rows) == 1
    r = rows[0]
    assert r["title"] == "Blue Dream | Live Resin | Aio | 1g"
    assert r["brand"] == "Stiiizy"
    assert r["weight"] == "1g"
    assert r["price"] == "45"
    assert r["thc"] == "85"
    assert r["product_url"].endswith("/products/abc")
    assert r["platform"] == "Dutchie"
    assert r["batch_id"] == "b1"


def test_weedmaps_adapter_extracts_scalar_price():
    pages = [
        {"__paged__": True, "data": {"menu_items": [{
            "id": "w1", "name": "STIIIZY Biscotti 1g",
            "brand_endorsement": {"brand_name": "STIIIZY"},
            "category": {"name": "Vaporizers"},
            "price": {"price": 45.0, "label": "each"}}]},
            "meta": {"total_menu_items": 1}},
        {"__paged__": True, "data": {"menu_items": []}, "meta": {"total_menu_items": 1}},
    ]
    e = _entry(platform="weedmaps", ext="ether", raw="WeedMaps",
               menu="https://etherbuffalo.wm.store/")
    rows = adapters.fetch_weedmaps(e, FixtureClient({"menu_items": pages}), "b")
    assert len(rows) == 1
    assert rows[0]["brand"] == "STIIIZY"
    assert rows[0]["price"] == "45.0"


def test_carrot_requires_host_key_index():
    e = _entry(platform="carrot", ext="bad_format", raw="Carrot")
    try:
        adapters.fetch_carrot(e, FixtureClient({}), "b")
        assert False, "should have raised"
    except ValueError:
        pass


def test_carrot_adapter_paginates():
    pages = [
        {"__paged__": True, "hits": [{"document": {
            "id": "p1", "name": "Gummies 100mg", "brand": "Ayrloom",
            "category": "Edibles", "price": 12}}]},
        {"__paged__": True, "hits": []},
    ]
    e = _entry(platform="carrot", ext="host|KEY|menu", raw="Carrot")
    rows = adapters.fetch_carrot(e, FixtureClient({"documents/search": pages}), "b")
    assert len(rows) == 1
    assert rows[0]["brand"] == "Ayrloom"
    assert rows[0]["category"] == "Edibles"


def test_platform_alias_normalization():
    assert PLATFORM_ALIASES["proteus420"] == "proteus"
    assert PLATFORM_ALIASES["aiq"] == "dispense"
    assert PLATFORM_ALIASES["custom"] == "kushmart"


def test_runner_skips_unrunnable_and_unknown(tmp_path):
    class _Sink:
        def __init__(self): self.rows = []
        def write(self, rows): self.rows.extend(rows)
        def close(self): return len(self.rows)

    entries = [
        _entry(),                                        # dutchie, runnable
        DispensaryEntry("Blank", "dutchie", "Dutchie", "", "", ""),  # missing id
        DispensaryEntry("HtmlShop", "proteus", "Proteus420", "x", "", ""),  # no adapter
    ]
    pages = [{"__paged__": True, "data": {"filteredProducts": {
        "products": [{"id": "a", "Name": "X", "type": "Flower"}],
        "queryInfo": {"totalPages": 1}}}}]
    sink = _Sink()
    res = harvest(entries, sink, client=FixtureClient({"graphql": pages}), batch_id="b")
    assert res.stores_ok == 1
    assert res.stores_skipped == 2
    assert res.listings == 1


def test_registry_loads_real_csv():
    entries = load_registry("data/dispensaries.csv")
    assert len(entries) > 30
    platforms = {e.platform for e in entries}
    assert "dutchie" in platforms and "carrot" in platforms
