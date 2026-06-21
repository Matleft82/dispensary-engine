"""Harvest runner: registry -> per-platform adapter -> sink.

A store failure is logged and skipped; it never aborts the batch. Platforms
without a JSON adapter yet (HTML scrapers) are reported as skipped with a reason.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import ADAPTERS, HTML_PLATFORMS
from .delta import MenuStateStore, append_price_history, diff
from .http import HttpClient
from .registry import DispensaryEntry, load_registry


@dataclass
class HarvestResult:
    batch_id: str
    started_at: str
    stores_total: int = 0
    stores_ok: int = 0
    stores_skipped: int = 0
    stores_failed: int = 0
    listings: int = 0
    per_store: list[dict] = field(default_factory=list)
    # incremental-mode aggregates
    incremental: bool = False
    added: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    price_changes: int = 0

    def to_dict(self) -> dict:
        return {**self.__dict__}


def new_batch_id() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + \
        "_" + uuid.uuid4().hex[:6]


def harvest(entries: list[DispensaryEntry], sink, client=None,
            batch_id: str | None = None, platforms: set[str] | None = None,
            limit: int | None = None, state_store: MenuStateStore | None = None,
            delta_sink=None, price_history_path=None) -> HarvestResult:
    """Harvest menus into the sink. If ``state_store`` is given, run incrementally:
    diff each store against its last snapshot, route only added/changed rows to
    ``delta_sink`` (and removed product_ids), append price moves to history, and
    update the snapshot. The full sink still receives the current menu so a full
    snapshot stays available."""
    client = client or HttpClient()
    batch_id = batch_id or new_batch_id()
    result = HarvestResult(batch_id=batch_id, incremental=state_store is not None,
                           started_at=_dt.datetime.now(_dt.timezone.utc).isoformat())

    selected = [e for e in entries
                if (platforms is None or e.platform in platforms)]
    if limit:
        selected = selected[:limit]
    result.stores_total = len(selected)

    for entry in selected:
        rec = {"dispensary": entry.name, "platform": entry.raw_platform,
               "status": None, "listings": 0, "error": None}
        if not entry.runnable:
            rec["status"] = "skipped"
            rec["error"] = "missing platform/external_id in registry"
            result.stores_skipped += 1
            result.per_store.append(rec)
            continue
        adapter = ADAPTERS.get(entry.platform)
        if adapter is None:
            rec["status"] = "skipped"
            rec["error"] = ("html-scraper platform not yet implemented"
                            if entry.platform in HTML_PLATFORMS
                            else f"no adapter for platform '{entry.platform}'")
            result.stores_skipped += 1
            result.per_store.append(rec)
            continue
        try:
            rows = adapter(entry, client, batch_id)
            sink.write(rows)
            rec["status"] = "ok"
            rec["listings"] = len(rows)
            result.stores_ok += 1
            result.listings += len(rows)
            if state_store is not None:
                d = diff(state_store.load(entry.external_id), rows, entry.external_id)
                rec["delta"] = d.summary()
                result.added += len(d.added)
                result.changed += len(d.changed)
                result.removed += len(d.removed)
                result.unchanged += d.unchanged
                if delta_sink is not None:
                    delta_sink.write(d.changed_rows)
                    delta_sink.add_removed(d.removed, entry.external_id)
                if price_history_path is not None:
                    result.price_changes += append_price_history(
                        price_history_path, d.price_changes)
                state_store.save(entry.external_id, rows)
        except Exception as exc:  # network/anti-bot/parse error -> skip store
            rec["status"] = "failed"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            result.stores_failed += 1
        result.per_store.append(rec)

    return result


def run_from_csv(csv_path: str | Path, out_json: str | Path, client=None,
                 incremental: bool = False, state_dir: str | Path = "state",
                 delta_json: str | Path | None = None,
                 price_history: str | Path | None = None, **kwargs) -> HarvestResult:
    from .sinks import DeltaSink, JsonSink
    entries = load_registry(csv_path)
    sink = JsonSink(out_json)
    state_store = MenuStateStore(state_dir) if incremental else None
    delta_sink = DeltaSink(delta_json) if (incremental and delta_json) else None
    if incremental and price_history is None:
        price_history = Path(out_json).parent / "price_history.jsonl"
    result = harvest(entries, sink, client=client, state_store=state_store,
                     delta_sink=delta_sink, price_history_path=price_history,
                     **kwargs)
    result.listings = sink.close()
    if delta_sink is not None:
        delta_sink.close()
    return result
