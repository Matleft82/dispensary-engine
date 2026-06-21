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

    def to_dict(self) -> dict:
        return {**self.__dict__}


def new_batch_id() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + \
        "_" + uuid.uuid4().hex[:6]


def harvest(entries: list[DispensaryEntry], sink, client=None,
            batch_id: str | None = None, platforms: set[str] | None = None,
            limit: int | None = None) -> HarvestResult:
    client = client or HttpClient()
    batch_id = batch_id or new_batch_id()
    result = HarvestResult(batch_id=batch_id,
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
        except Exception as exc:  # network/anti-bot/parse error -> skip store
            rec["status"] = "failed"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            result.stores_failed += 1
        result.per_store.append(rec)

    return result


def run_from_csv(csv_path: str | Path, out_json: str | Path,
                 client=None, **kwargs) -> HarvestResult:
    from .sinks import JsonSink
    entries = load_registry(csv_path)
    sink = JsonSink(out_json)
    result = harvest(entries, sink, client=client, **kwargs)
    result.listings = sink.close()
    return result
