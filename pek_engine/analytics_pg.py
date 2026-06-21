"""Postgres sink for the time-series archive.

Loads the compacted archive (current_state + retained events + daily/monthly
rollups) into a database. All upserts are idempotent (``ON CONFLICT``), so a tick
can be re-run safely. SQLAlchemy is imported lazily; the same Core SQL runs on
Postgres and SQLite (used by the tests), so no live Postgres is needed to verify.

Schema (prices in integer cents, keyed on the canonical MCP id):
  current_state   one row per live product               PK (mcp_id, dispensary)
  price_events    append-only change log                 PK event_id (dedup)
  daily_rollup    OHLC per product/dispensary/day         PK (mcp_id, dispensary_id, day)
  monthly_rollup  aggregates per product/dispensary/month PK (mcp_id, dispensary_id, month)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_DDL = [
    """CREATE TABLE IF NOT EXISTS current_state (
        mcp_id TEXT, dispensary TEXT, canonical_title TEXT,
        price_cents INTEGER, in_stock TEXT, product_url TEXT,
        updated_at TEXT, PRIMARY KEY (mcp_id, dispensary))""",
    """CREATE TABLE IF NOT EXISTS price_events (
        event_id TEXT PRIMARY KEY, mcp_id TEXT, dispensary_id TEXT,
        product_id TEXT, canonical_title TEXT, old_cents INTEGER,
        new_cents INTEGER, observed_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS daily_rollup (
        mcp_id TEXT, dispensary_id TEXT, day TEXT, canonical_title TEXT,
        open_cents INTEGER, high_cents INTEGER, low_cents INTEGER,
        close_cents INTEGER, avg_cents INTEGER, changes INTEGER,
        PRIMARY KEY (mcp_id, dispensary_id, day))""",
    """CREATE TABLE IF NOT EXISTS monthly_rollup (
        mcp_id TEXT, dispensary_id TEXT, month TEXT, canonical_title TEXT,
        open_cents INTEGER, high_cents INTEGER, low_cents INTEGER,
        close_cents INTEGER, avg_cents INTEGER, active_days INTEGER,
        changes INTEGER, PRIMARY KEY (mcp_id, dispensary_id, month))""",
]


def _event_id(ev: dict) -> str:
    base = f"{ev.get('mcp_id')}|{ev.get('dispensary_id')}|{ev.get('observed_at')}|{ev.get('new_cents')}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


class ArchiveDB:
    def __init__(self, dsn: str) -> None:
        from sqlalchemy import create_engine
        self._engine = create_engine(dsn)
        self._is_sqlite = self._engine.dialect.name == "sqlite"
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        from sqlalchemy import text
        with self._engine.begin() as conn:
            for ddl in _DDL:
                conn.execute(text(ddl))

    def _upsert(self, table: str, pk_cols: list[str], rows: list[dict]) -> int:
        if not rows:
            return 0
        from sqlalchemy import text
        cols = list(rows[0].keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        update_cols = [c for c in cols if c not in pk_cols]
        set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
        conflict = ", ".join(pk_cols)
        if update_cols:
            action = f"DO UPDATE SET {set_clause}"
        else:
            action = "DO NOTHING"
        stmt = text(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) {action}")
        with self._engine.begin() as conn:
            for r in rows:
                conn.execute(stmt, {c: r.get(c) for c in cols})
        return len(rows)

    def upsert_current_state(self, rows: list[dict]) -> int:
        norm = [{"mcp_id": r["mcp_id"], "dispensary": r["dispensary"],
                 "canonical_title": r.get("canonical_title"),
                 "price_cents": r.get("price_cents"),
                 "in_stock": None if r.get("in_stock") is None else str(r.get("in_stock")),
                 "product_url": r.get("product_url"),
                 "updated_at": r.get("updated_at", "")} for r in rows if r.get("mcp_id")]
        return self._upsert("current_state", ["mcp_id", "dispensary"], norm)

    def append_events(self, events: list[dict]) -> int:
        norm = [{"event_id": _event_id(e), "mcp_id": e.get("mcp_id"),
                 "dispensary_id": e.get("dispensary_id"),
                 "product_id": e.get("product_id"),
                 "canonical_title": e.get("canonical_title"),
                 "old_cents": e.get("old_cents"), "new_cents": e.get("new_cents"),
                 "observed_at": e.get("observed_at")}
                for e in events if e.get("mcp_id")]
        return self._upsert("price_events", ["event_id"], norm)

    def upsert_daily(self, rows: list[dict]) -> int:
        return self._upsert("daily_rollup", ["mcp_id", "dispensary_id", "day"],
                            [r for r in rows if r.get("mcp_id")])

    def upsert_monthly(self, rows: list[dict]) -> int:
        return self._upsert("monthly_rollup", ["mcp_id", "dispensary_id", "month"],
                            [r for r in rows if r.get("mcp_id")])

    def sync_from_dir(self, archive_dir: str | Path) -> dict:
        """Load the file-based archive (produced by analytics.compact) into the DB."""
        from . import analytics
        arc = Path(archive_dir)
        return {
            "current_state": self.upsert_current_state(
                analytics.load_jsonl(arc / "current_state.jsonl")),
            "price_events": self.append_events(
                analytics.load_jsonl(arc / "price_history.jsonl")),
            "daily_rollup": self.upsert_daily(
                analytics.load_jsonl(arc / "daily_rollup.jsonl")),
            "monthly_rollup": self.upsert_monthly(
                analytics.load_jsonl(arc / "monthly_rollup.jsonl")),
        }
