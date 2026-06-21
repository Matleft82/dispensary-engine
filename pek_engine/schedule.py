"""Scheduler that drives the N×/day harvest cadence.

Each tick runs the full incremental cycle:

    scrape (incremental) -> normalize (incremental) -> archive (+ optional Postgres)

The first tick (no prior outputs) does a full normalize to seed the baseline;
every tick after that only re-normalizes the delta. Run it as a long-lived loop
(`--times-per-day N`) or as a single `--once` tick wired to system cron.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ScheduleConfig:
    dispensaries: str = "data/dispensaries.csv"
    brands: str = "data/brand_aliases_seed.csv"
    raw_out: str = "data/raw_listings.json"
    out_dir: str = "outputs"
    state_dir: str = "state"
    delta_json: str = "data/delta.json"
    archive_dir: str = "archive"
    price_history: str = "outputs/price_history.jsonl"
    platforms: set[str] | None = None
    limit: int | None = None
    dsn: str | None = None
    recent_days: int = 90
    daily_months: int = 13
    jitter_seconds: int = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_tick(cfg: ScheduleConfig, client=None) -> dict:
    """One harvest cycle. Returns a structured summary for logging/telemetry."""
    from .pipeline import run as run_normalize
    from .pipeline import run_incremental
    from .scrape import run_from_csv

    started = _now()
    harvest = run_from_csv(
        cfg.dispensaries, cfg.raw_out, client=client, platforms=cfg.platforms,
        limit=cfg.limit, incremental=True, state_dir=cfg.state_dir,
        delta_json=cfg.delta_json, price_history=cfg.price_history)

    seeded = Path(cfg.out_dir, "normalized_dpls.json").exists()
    if seeded:
        norm = run_incremental(cfg.out_dir, cfg.delta_json, cfg.brands,
                               cfg.dispensaries, cfg.out_dir)
        norm_mode = "incremental"
    else:
        norm = run_normalize(cfg.raw_out, cfg.brands, cfg.dispensaries, cfg.out_dir)
        norm_mode = "full"

    archive = _archive(cfg)

    return {"started_at": started, "finished_at": _now(),
            "harvest": {k: harvest.to_dict().get(k) for k in
                        ("listings", "added", "changed", "removed", "unchanged",
                         "price_changes", "stores_ok", "stores_failed")},
            "normalize_mode": norm_mode,
            "mcps": norm.get("new_mcps_created"),
            "archive": archive}


def _archive(cfg: ScheduleConfig) -> dict:
    import shutil

    from . import analytics
    events = analytics.load_jsonl(cfg.price_history)
    Path(cfg.archive_dir).mkdir(parents=True, exist_ok=True)
    if events:
        events = analytics.enrich_events_with_mcp(events, cfg.out_dir)
        analytics.write_jsonl(cfg.price_history, events)
    analytics.write_jsonl(Path(cfg.archive_dir) / "current_state.jsonl",
                          analytics.build_current_state(cfg.out_dir))
    dst = Path(cfg.archive_dir) / "price_history.jsonl"
    src = Path(cfg.price_history)
    if src.exists() and src.resolve() != dst.resolve():
        shutil.copy(src, dst)
    elif not dst.exists():
        dst.write_text("")
    stats = analytics.compact(cfg.archive_dir, recent_days=cfg.recent_days,
                              daily_months=cfg.daily_months)
    if cfg.dsn:
        from .analytics_pg import ArchiveDB
        stats["postgres"] = ArchiveDB(cfg.dsn).sync_from_dir(cfg.archive_dir)
    return stats


def run_scheduler(cfg: ScheduleConfig, times_per_day: int = 3,
                  max_ticks: int | None = None, sleep_fn=time.sleep,
                  log_fn=None) -> list[dict]:
    """Loop forever (or for ``max_ticks``) running one tick per interval.

    Interval = 24h / times_per_day, plus optional random jitter to avoid
    hammering every store at the same instant each cycle."""
    interval = max(1, int(86400 / max(1, times_per_day)))
    log_fn = log_fn or (lambda m: print(json.dumps(m)))
    summaries: list[dict] = []
    tick = 0
    while max_ticks is None or tick < max_ticks:
        tick += 1
        try:
            summary = run_tick(cfg)
            summary["tick"] = tick
            log_fn(summary)
            summaries.append(summary)
        except Exception as exc:  # a tick failure must not kill the scheduler
            log_fn({"tick": tick, "error": f"{type(exc).__name__}: {exc}"})
        if max_ticks is not None and tick >= max_ticks:
            break
        delay = interval + (random.randint(0, cfg.jitter_seconds)
                            if cfg.jitter_seconds else 0)
        sleep_fn(delay)
    return summaries
