"""Tests for incremental harvest, delta diffing, incremental normalize, and the
time-series archival rollups/compaction."""

import json
from pathlib import Path

from pek_engine import analytics, pipeline
from pek_engine.scrape import DeltaSink, MenuStateStore, diff, harvest
from pek_engine.scrape.delta import content_hash
from pek_engine.scrape.http import FixtureClient
from pek_engine.scrape.registry import DispensaryEntry

DATA = Path(__file__).resolve().parent.parent / "data"


def _row(pid, price, title="Stiiizy Blue Dream Pod 1g", **kw):
    base = {"product_id": pid, "dispensary_id": "d1", "title": title,
            "brand": "Stiiizy", "category": "Vaporizers", "weight": "1g",
            "price": str(price), "image": "", "thc": "85", "thc_unit": "PERCENTAGE",
            "strain_type": "Hybrid", "original_subcategory": "Cart", "cbd": "",
            "cbd_unit": "", "product_url": f"http://x/{pid}"}
    base.update(kw)
    return base


def test_content_hash_ignores_volatile_fields():
    a = _row("p1", 45)
    b = dict(a, scraped_at="2026-01-01", batch_id="zzz")
    assert content_hash(a) == content_hash(b)
    assert content_hash(a) != content_hash(_row("p1", 40))


def test_diff_classifies_added_changed_removed_unchanged():
    prev = {r["product_id"]: {"hash": content_hash(r), "price": r["price"],
                              "title": r["title"]}
            for r in [_row("p1", 45), _row("p2", 30), _row("p3", 20)]}
    current = [_row("p1", 45), _row("p2", 25), _row("p4", 10)]  # p3 removed, p4 new
    d = diff(prev, current, "d1")
    assert [r["product_id"] for r in d.added] == ["p4"]
    assert [r["product_id"] for r in d.changed] == ["p2"]
    assert d.removed == ["p3"]
    assert d.unchanged == 1
    assert d.price_changes[0]["old_price"] == "30"
    assert d.price_changes[0]["new_price"] == "25"


def _entry():
    return DispensaryEntry(name="Shop", platform="dutchie", raw_platform="Dutchie",
                           external_id="d1", menu_url="http://m", website="http://w")


def _fixture_client(rows):
    pages = [{"__paged__": True,
              "data": {"filteredProducts": {
                  "products": [{"_id": r["product_id"], "Name": r["title"],
                                "brandName": r["brand"], "type": r["category"],
                                "subcategory": "Cart", "strainType": "Hybrid",
                                "THCContent": {"range": [85], "unit": "PERCENTAGE"},
                                "Options": [r["weight"]], "recPrices": [float(r["price"])],
                                "Image": ""} for r in rows],
                  "queryInfo": {"totalPages": 1}}}}]
    return FixtureClient({"graphql": pages})


def test_incremental_harvest_only_emits_changes(tmp_path):
    state = MenuStateStore(tmp_path / "state")
    ph = tmp_path / "price_history.jsonl"

    class _Null:
        def write(self, rows): pass
        def close(self): return 0

    # first pull: everything is new
    delta1 = DeltaSink(tmp_path / "d1.json")
    r1 = harvest([_entry()], _Null(), client=_fixture_client([_row("p1", 45), _row("p2", 30)]),
                 state_store=state, delta_sink=delta1, price_history_path=ph)
    assert (r1.added, r1.changed, r1.removed, r1.unchanged) == (2, 0, 0, 0)

    # second pull: p1 unchanged, p2 price moved
    delta2 = DeltaSink(tmp_path / "d2.json")
    r2 = harvest([_entry()], _Null(), client=_fixture_client([_row("p1", 45), _row("p2", 28)]),
                 state_store=state, delta_sink=delta2, price_history_path=ph)
    assert (r2.added, r2.changed, r2.removed, r2.unchanged) == (0, 1, 0, 1)
    assert r2.price_changes == 1
    out = delta2.close()
    assert out == {"changed": 1, "removed": 0}
    payload = json.loads((tmp_path / "d2.json").read_text())
    assert payload["changed_listings"][0]["product_id"] == "p2"
    # price_history is append-only: 2 events (both initial adds count as price moves? no)
    events = analytics.load_jsonl(ph)
    assert len(events) == 1 and events[0]["new_value"] == 28.0


def test_incremental_normalize_matches_full_run(tmp_path):
    rows = [_row("p1", 45), _row("p2", 30, title="Stiiizy Gelato Pod 1g")]
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps(rows))
    prev = tmp_path / "prev"
    pipeline.run(str(raw), str(DATA / "brand_aliases_seed.csv"),
                 str(DATA / "dispensaries.csv"), str(prev))
    n_prev = len(json.loads((prev / "normalized_dpls.json").read_text()))

    # delta: p2 changes price, p3 added, p1 removed
    delta = {"changed_listings": [_row("p2", 25, title="Stiiizy Gelato Pod 1g"),
                                  _row("p3", 12, title="Stiiizy Wedding Cake Pod 1g")],
             "removed_product_ids": [{"dispensary_id": "d1", "product_id": "p1"}]}
    djson = tmp_path / "delta.json"
    djson.write_text(json.dumps(delta))
    out = tmp_path / "out"
    summary = pipeline.run_incremental(str(prev), str(djson),
                                       str(DATA / "brand_aliases_seed.csv"),
                                       str(DATA / "dispensaries.csv"), str(out))
    assert summary["incremental"]["re_normalized"] == 2
    assert summary["incremental"]["removed"] == 1
    # p1 dropped, p2 + p3 present -> 2 normalized
    n_now = len(json.loads((out / "normalized_dpls.json").read_text()))
    assert n_now == 2 == n_prev  # started with 2, removed 1, added 1


def test_archival_rollups_and_compaction(tmp_path):
    events = [
        {"product_id": "p1", "dispensary_id": "d1", "mcp_id": "m1",
         "canonical_title": "X", "old_value": 45.0, "new_value": 40.0,
         "observed_at": "2026-01-10T08:00:00+00:00"},
        {"product_id": "p1", "dispensary_id": "d1", "mcp_id": "m1",
         "canonical_title": "X", "old_value": 40.0, "new_value": 42.0,
         "observed_at": "2026-01-10T20:00:00+00:00"},
        {"product_id": "p1", "dispensary_id": "d1", "mcp_id": "m1",
         "canonical_title": "X", "old_value": 42.0, "new_value": 38.0,
         "observed_at": "2026-03-15T09:00:00+00:00"},
    ]
    for e in events:
        e["old_cents"] = analytics.to_cents(e["old_value"])
        e["new_cents"] = analytics.to_cents(e["new_value"])
    daily = analytics.roll_up_daily(events)
    jan = [d for d in daily if d["day"] == "2026-01-10"][0]
    assert jan["open_cents"] == 4500 and jan["close_cents"] == 4200
    assert jan["high_cents"] == 4200 and jan["low_cents"] == 4000
    assert jan["changes"] == 2

    monthly = analytics.roll_up_monthly(daily)
    assert {m["month"] for m in monthly} == {"2026-01", "2026-03"}

    # compaction: with "today" in June, Jan events (>90d) fold into daily
    analytics.write_jsonl(tmp_path / "price_history.jsonl", events)
    stats = analytics.compact(tmp_path, recent_days=90, daily_months=13,
                              today="2026-05-01")
    assert stats["events_folded"] == 2  # the two Jan events (>90d old)
    assert stats["events_retained"] == 1  # the March event (within 90d)
    assert analytics.load_jsonl(tmp_path / "daily_rollup.jsonl")
