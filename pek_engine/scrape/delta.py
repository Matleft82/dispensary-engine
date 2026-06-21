"""Incremental harvest: diff each pull against the last and act only on changes.

The menu APIs have no universal "changed since" feed, so a pull still fetches the
current menu — but everything downstream is incremental. Each product is reduced
to a stable content fingerprint; comparing fingerprints to the last snapshot
classifies every product as added / changed / removed / unchanged. Only the
changes are emitted for re-normalization, and every price move is appended to a
price-history log."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Fields whose change means the product materially changed. Excludes volatile
# bookkeeping (scraped_at, batch_id) so an identical menu yields zero changes.
_FINGERPRINT_FIELDS = (
    "title", "brand", "category", "original_subcategory", "strain_type",
    "thc", "thc_unit", "cbd", "cbd_unit", "weight", "price", "image",
    "product_url",
)


def content_hash(row: dict) -> str:
    payload = "|".join(f"{k}={row.get(k, '')}" for k in _FINGERPRINT_FIELDS)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _price(row: dict):
    s = str(row.get("price", "")).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class Delta:
    dispensary_id: str
    added: list[dict] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)      # current rows
    removed: list[str] = field(default_factory=list)       # product_ids
    unchanged: int = 0
    price_changes: list[dict] = field(default_factory=list)

    @property
    def changed_rows(self) -> list[dict]:
        """Rows that must be re-normalized (added + changed)."""
        return self.added + self.changed

    def summary(self) -> dict:
        return {"dispensary_id": self.dispensary_id, "added": len(self.added),
                "changed": len(self.changed), "removed": len(self.removed),
                "unchanged": self.unchanged, "price_changes": len(self.price_changes)}


class MenuStateStore:
    """Per-dispensary snapshot of {product_id: {hash, price, title}}."""

    def __init__(self, state_dir: str | Path) -> None:
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, dispensary_id: str) -> Path:
        safe = dispensary_id.replace("/", "_").replace("|", "_") or "unknown"
        return self.dir / f"{safe}.json"

    def load(self, dispensary_id: str) -> dict[str, dict]:
        p = self._path(dispensary_id)
        if not p.exists():
            return {}
        return json.loads(p.read_text())

    def save(self, dispensary_id: str, rows: list[dict]) -> None:
        state = {r["product_id"]: {"hash": content_hash(r), "price": r.get("price"),
                                   "title": r.get("title")} for r in rows}
        self._path(dispensary_id).write_text(
            json.dumps(state, ensure_ascii=False, indent=0))


def diff(previous: dict[str, dict], current_rows: list[dict],
         dispensary_id: str) -> Delta:
    """Classify current rows against the previous snapshot."""
    d = Delta(dispensary_id=dispensary_id)
    seen: set[str] = set()
    for row in current_rows:
        pid = row.get("product_id", "")
        seen.add(pid)
        prev = previous.get(pid)
        h = content_hash(row)
        if prev is None:
            d.added.append(row)
        elif prev.get("hash") != h:
            d.changed.append(row)
            old_price, new_price = prev.get("price"), row.get("price")
            if str(old_price) != str(new_price):
                d.price_changes.append({
                    "product_id": pid, "title": row.get("title"),
                    "dispensary_id": dispensary_id,
                    "old_price": old_price, "new_price": new_price,
                    "old_value": _price({"price": old_price}),
                    "new_value": _price(row),
                    "observed_at": datetime.now(timezone.utc).isoformat()})
        else:
            d.unchanged += 1
    d.removed = [pid for pid in previous if pid not in seen]
    return d


def append_price_history(path: str | Path, price_changes: list[dict]) -> int:
    if not price_changes:
        return 0
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        for row in price_changes:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(price_changes)
