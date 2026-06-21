"""Sinks for harvested listings: JSON file (default) and Postgres (optional)."""

from __future__ import annotations

import json
from pathlib import Path


class JsonSink:
    """Write all harvested rows to one JSON file (the engine's input schema)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._rows: list[dict] = []

    def write(self, rows: list[dict]) -> None:
        self._rows.extend(rows)

    def close(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._rows, ensure_ascii=False, indent=0))
        return len(self._rows)


class DeltaSink:
    """Write only the incremental changes: added/changed rows + removed ids."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._rows: list[dict] = []
        self._removed: list[str] = []

    def write(self, rows: list[dict]) -> None:
        self._rows.extend(rows)

    def add_removed(self, product_ids: list[str], dispensary_id: str = "") -> None:
        self._removed.extend({"dispensary_id": dispensary_id, "product_id": pid}
                             for pid in product_ids)

    def close(self) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"changed_listings": self._rows, "removed_product_ids": self._removed}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=0))
        return {"changed": len(self._rows), "removed": len(self._removed)}


class PostgresSink:
    """Upsert rows into a ``dispensary_products`` table (requires sqlalchemy)."""

    def __init__(self, dsn: str) -> None:
        from sqlalchemy import create_engine  # imported lazily
        self._engine = create_engine(dsn)
        self._count = 0
        self._ensure_table()

    def _ensure_table(self) -> None:
        from sqlalchemy import text
        with self._engine.begin() as conn:
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS dispensary_products (
                    id TEXT PRIMARY KEY,
                    store_id TEXT, store_name TEXT, platform TEXT,
                    name TEXT, brand TEXT, category TEXT,
                    price TEXT, product_url TEXT, image TEXT,
                    raw_data JSONB, batch_id TEXT,
                    last_updated TIMESTAMPTZ DEFAULT NOW()
                )
                """
            ))

    def write(self, rows: list[dict]) -> None:
        from sqlalchemy import text
        stmt = text(
            """
            INSERT INTO dispensary_products
              (id, store_id, store_name, platform, name, brand, category,
               price, product_url, image, raw_data, batch_id, last_updated)
            VALUES
              (:id, :sid, :sname, :plat, :name, :brand, :cat, :price, :url,
               :img, :raw, :batch, NOW())
            ON CONFLICT (id) DO UPDATE SET
              name=EXCLUDED.name, brand=EXCLUDED.brand, category=EXCLUDED.category,
              price=EXCLUDED.price, product_url=EXCLUDED.product_url,
              image=EXCLUDED.image, raw_data=EXCLUDED.raw_data,
              batch_id=EXCLUDED.batch_id, last_updated=NOW()
            """
        )
        with self._engine.begin() as conn:
            for r in rows:
                conn.execute(stmt, {
                    "id": f"{r['dispensary_id']}_{r['product_id']}",
                    "sid": r["dispensary_id"], "sname": r["dispensary"],
                    "plat": r.get("platform", ""), "name": r["title"],
                    "brand": r["brand"], "cat": r["category"],
                    "price": r["price"], "url": r.get("product_url", ""),
                    "img": r["image"], "raw": json.dumps(r.get("raw_data", {})),
                    "batch": r.get("batch_id", ""),
                })
                self._count += 1

    def close(self) -> int:
        return self._count
