"""Time-series archival for menus, built for analytics-over-time without bloat.

A price is a step function, so its entire history is reconstructable from just the
change-points. We therefore never archive full menu snapshots; we keep:

  Tier 0  current_state   one row per live product (overwritten each pull)
  Tier 1  events          append-only, only when something changes (lossless)
  Tier 2  daily rollup    OHLC per (mcp, dispensary, day-with-a-change)
  Tier 3  monthly rollup  aggregates per (mcp, dispensary, month)

Compaction folds events older than a retention window into the daily rollup (and
daily into monthly), so storage stays roughly constant instead of growing
linearly with pulls. Everything keys on the canonical MCP id (not per-store
product GUIDs, which explode cardinality) and prices are stored as integer cents."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .ingest import raw_id


def to_cents(price) -> int | None:
    if price in (None, "", "None"):
        return None
    try:
        return int(round(float(str(price).replace("$", "").replace(",", "")) * 100))
    except (ValueError, TypeError):
        return None


def _dpl_id(dispensary_id: str, product_id: str) -> str:
    return "dpl_" + raw_id(dispensary_id, product_id).removeprefix("raw_")


def load_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def write_jsonl(path: str | Path, rows: list[dict]) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def enrich_events_with_mcp(events: list[dict], out_dir: str | Path) -> list[dict]:
    """Attach canonical mcp_id + title to each price event using the batch's
    mcp_dpl_links + master_canonical_products. Events that can't be mapped (e.g.
    an excluded accessory) keep mcp_id=None and fall back to a per-store key."""
    out = Path(out_dir)
    links = json.loads((out / "mcp_dpl_links.json").read_text())
    mcps = json.loads((out / "master_canonical_products.json").read_text())
    mcp_by_id = {m["mcp_id"]: m for m in mcps}
    mcp_by_dpl = {l["dpl_id"]: l["mcp_id"] for l in links}
    for ev in events:
        dpl_id = _dpl_id(ev.get("dispensary_id", ""), ev.get("product_id", ""))
        mcp_id = mcp_by_dpl.get(dpl_id)
        ev["mcp_id"] = mcp_id
        ev["canonical_title"] = (mcp_by_id.get(mcp_id) or {}).get("canonical_title")
        ev["old_cents"] = to_cents(ev.get("old_value", ev.get("old_price")))
        ev["new_cents"] = to_cents(ev.get("new_value", ev.get("new_price")))
    return events


def _series_key(ev: dict) -> tuple[str, str]:
    """Analytics key: canonical product at a dispensary."""
    return (ev.get("mcp_id") or f"prod:{ev.get('product_id')}",
            ev.get("dispensary_id", ""))


def _day(ts: str) -> str:
    return (ts or "")[:10]


def _month(ts: str) -> str:
    return (ts or "")[:7]


def roll_up_daily(events: list[dict]) -> list[dict]:
    """OHLC per (mcp_id, dispensary, day) — only days where a change occurred.
    On no-change days the price equals the previous row's close (step function),
    so omitting them is lossless."""
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for ev in events:
        buckets[(*_series_key(ev), _day(ev.get("observed_at", "")))].append(ev)
    rows: list[dict] = []
    for (mcp_id, disp, day), evs in sorted(buckets.items()):
        evs.sort(key=lambda e: e.get("observed_at", ""))
        cents = [e["new_cents"] for e in evs if e.get("new_cents") is not None]
        if not cents:
            continue
        opens = next((e["old_cents"] for e in evs if e.get("old_cents") is not None),
                     cents[0])
        rows.append({
            "mcp_id": mcp_id, "dispensary_id": disp, "day": day,
            "canonical_title": evs[-1].get("canonical_title"),
            "open_cents": opens, "high_cents": max(cents), "low_cents": min(cents),
            "close_cents": cents[-1],
            "avg_cents": round(sum(cents) / len(cents)),
            "changes": len(evs)})
    return rows


def roll_up_monthly(daily_rows: list[dict]) -> list[dict]:
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for r in daily_rows:
        buckets[(r["mcp_id"], r["dispensary_id"], r["day"][:7])].append(r)
    rows: list[dict] = []
    for (mcp_id, disp, month), drs in sorted(buckets.items()):
        drs.sort(key=lambda r: r["day"])
        rows.append({
            "mcp_id": mcp_id, "dispensary_id": disp, "month": month,
            "canonical_title": drs[-1].get("canonical_title"),
            "open_cents": drs[0]["open_cents"],
            "high_cents": max(r["high_cents"] for r in drs),
            "low_cents": min(r["low_cents"] for r in drs),
            "close_cents": drs[-1]["close_cents"],
            "avg_cents": round(sum(r["avg_cents"] for r in drs) / len(drs)),
            "active_days": len(drs),
            "changes": sum(r["changes"] for r in drs)})
    return rows


def compact(archive_dir: str | Path, events_filename: str = "price_history.jsonl",
            recent_days: int = 90, daily_months: int = 13,
            today: str | None = None) -> dict:
    """Fold events older than ``recent_days`` into the daily rollup and drop them;
    fold daily rows older than ``daily_months`` into the monthly rollup. Keeps the
    raw event log bounded while preserving full history at coarser granularity."""
    import datetime as _dt
    arc = Path(archive_dir)
    now = _dt.date.fromisoformat(today) if today else _dt.date.today()
    event_cut = (now - _dt.timedelta(days=recent_days)).isoformat()
    daily_cut = (now - _dt.timedelta(days=daily_months * 30)).isoformat()[:7]

    events = load_jsonl(arc / events_filename)
    recent = [e for e in events if _day(e.get("observed_at", "")) >= event_cut]
    old = [e for e in events if _day(e.get("observed_at", "")) < event_cut]

    daily = _merge_daily(arc, roll_up_daily(old))
    write_jsonl(arc / events_filename, recent)

    keep_daily = [d for d in daily if d["day"][:7] >= daily_cut]
    old_daily = [d for d in daily if d["day"][:7] < daily_cut]
    monthly = _merge_monthly(arc, roll_up_monthly(old_daily))
    write_jsonl(arc / "daily_rollup.jsonl", keep_daily)
    write_jsonl(arc / "monthly_rollup.jsonl", monthly)

    return {"events_folded": len(old), "events_retained": len(recent),
            "daily_rows": len(keep_daily), "daily_folded": len(old_daily),
            "monthly_rows": len(monthly)}


def _merge_daily(arc: Path, new_rows: list[dict]) -> list[dict]:
    existing = load_jsonl(arc / "daily_rollup.jsonl")
    by_key = {(r["mcp_id"], r["dispensary_id"], r["day"]): r for r in existing}
    for r in new_rows:
        by_key[(r["mcp_id"], r["dispensary_id"], r["day"])] = r
    return sorted(by_key.values(), key=lambda r: (r["day"], str(r["mcp_id"])))


def _merge_monthly(arc: Path, new_rows: list[dict]) -> list[dict]:
    existing = load_jsonl(arc / "monthly_rollup.jsonl")
    by_key = {(r["mcp_id"], r["dispensary_id"], r["month"]): r for r in existing}
    for r in new_rows:
        by_key[(r["mcp_id"], r["dispensary_id"], r["month"])] = r
    return sorted(by_key.values(), key=lambda r: (r["month"], str(r["mcp_id"])))


def build_current_state(out_dir: str | Path) -> list[dict]:
    """Tier 0: one compact row per live product from the latest price index."""
    out = Path(out_dir)
    px = json.loads((out / "price_comparison_index.json").read_text())
    rows = []
    for p in px:
        rows.append({
            "mcp_id": p["mcp_id"], "dispensary": p["source_dispensary"],
            "canonical_title": p["canonical_title"],
            "price_cents": to_cents(p.get("effective_price")),
            "in_stock": p.get("in_stock"), "product_url": p.get("product_url")})
    return rows
