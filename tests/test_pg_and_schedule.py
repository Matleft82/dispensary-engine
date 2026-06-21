"""Postgres archival sink (verified on SQLite via the same SQLAlchemy Core SQL)
and the scheduler tick/loop."""

from pathlib import Path

import pytest

from pek_engine import analytics, schedule
from pek_engine.scrape.http import FixtureClient

DATA = Path(__file__).resolve().parent.parent / "data"


def _dsn(tmp_path):
    return f"sqlite:///{tmp_path / 'archive.db'}"


def _seed_archive(arc: Path):
    analytics.write_jsonl(arc / "current_state.jsonl", [
        {"mcp_id": "m1", "dispensary": "Shop A", "canonical_title": "X 1g",
         "price_cents": 4500, "in_stock": True, "product_url": "http://x"}])
    analytics.write_jsonl(arc / "price_history.jsonl", [
        {"mcp_id": "m1", "dispensary_id": "d1", "product_id": "p1",
         "canonical_title": "X 1g", "old_cents": 4500, "new_cents": 4000,
         "observed_at": "2026-06-18T09:00:00+00:00"}])
    analytics.write_jsonl(arc / "daily_rollup.jsonl", [
        {"mcp_id": "m1", "dispensary_id": "d1", "day": "2026-06-18",
         "canonical_title": "X 1g", "open_cents": 4500, "high_cents": 4500,
         "low_cents": 4000, "close_cents": 4000, "avg_cents": 4250, "changes": 1}])
    analytics.write_jsonl(arc / "monthly_rollup.jsonl", [
        {"mcp_id": "m1", "dispensary_id": "d1", "month": "2026-06",
         "canonical_title": "X 1g", "open_cents": 4500, "high_cents": 4500,
         "low_cents": 4000, "close_cents": 4000, "avg_cents": 4250,
         "active_days": 1, "changes": 1}])


def test_pg_sink_sync_and_idempotent(tmp_path):
    pytest.importorskip("sqlalchemy")
    from sqlalchemy import create_engine, text

    from pek_engine.analytics_pg import ArchiveDB
    arc = tmp_path / "archive"
    arc.mkdir()
    _seed_archive(arc)

    db = ArchiveDB(_dsn(tmp_path))
    counts = db.sync_from_dir(arc)
    assert counts == {"current_state": 1, "price_events": 1, "daily_rollup": 1,
                      "monthly_rollup": 1}

    # re-running the same archive must not duplicate (idempotent upserts)
    db.sync_from_dir(arc)
    eng = create_engine(_dsn(tmp_path))
    with eng.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM price_events")).scalar() == 1
        assert c.execute(text("SELECT COUNT(*) FROM current_state")).scalar() == 1
        price = c.execute(text("SELECT price_cents FROM current_state")).scalar()
        assert price == 4500
        # a new price event on a later pull appends a second row
    analytics.write_jsonl(arc / "price_history.jsonl", [
        {"mcp_id": "m1", "dispensary_id": "d1", "product_id": "p1",
         "canonical_title": "X 1g", "old_cents": 4000, "new_cents": 3800,
         "observed_at": "2026-06-19T09:00:00+00:00"}])
    db.sync_from_dir(arc)
    with eng.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM price_events")).scalar() == 2


def _dutchie_fixture():
    products = [{"_id": f"p{i}", "Name": f"Stiiizy Strain {i} Pod 1g",
                 "brandName": "Stiiizy", "type": "Vaporizers", "subcategory": "Cart",
                 "strainType": "Hybrid",
                 "THCContent": {"range": [85], "unit": "PERCENTAGE"},
                 "Options": ["1g"], "recPrices": [40 + i], "Image": ""}
                for i in range(3)]
    pages = [{"__paged__": True,
              "data": {"filteredProducts": {"products": products,
                                            "queryInfo": {"totalPages": 1}}}}]
    return FixtureClient({"graphql": pages})


def test_run_tick_end_to_end(tmp_path):
    cfg = schedule.ScheduleConfig(
        dispensaries=str(DATA / "dispensaries.csv"),
        brands=str(DATA / "brand_aliases_seed.csv"),
        raw_out=str(tmp_path / "raw.json"), out_dir=str(tmp_path / "out"),
        state_dir=str(tmp_path / "state"), delta_json=str(tmp_path / "delta.json"),
        archive_dir=str(tmp_path / "arc"),
        price_history=str(tmp_path / "out" / "price_history.jsonl"),
        platforms={"dutchie"}, limit=1)
    summary = schedule.run_tick(cfg, client=_dutchie_fixture())

    assert summary["normalize_mode"] == "full"  # first tick seeds baseline
    assert summary["harvest"]["added"] == 3
    assert summary["harvest"]["listings"] == 3
    assert summary["mcps"] >= 1
    assert Path(tmp_path / "out" / "normalized_dpls.json").exists()
    assert Path(tmp_path / "arc" / "current_state.jsonl").exists()
    assert "archive" in summary


def test_run_scheduler_loop_runs_n_ticks_and_survives_errors(monkeypatch):
    calls = {"n": 0}

    def fake_tick(cfg, client=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("transient store error")
        return {"ok": calls["n"]}

    monkeypatch.setattr(schedule, "run_tick", fake_tick)
    logs = []
    out = schedule.run_scheduler(schedule.ScheduleConfig(), times_per_day=24,
                                 max_ticks=3, sleep_fn=lambda s: None,
                                 log_fn=logs.append)
    # 3 ticks attempted; tick 2 errored but loop continued -> 2 successful summaries
    assert calls["n"] == 3
    assert len(out) == 2
    assert any("error" in entry for entry in logs)
