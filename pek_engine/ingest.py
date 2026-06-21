"""Ingest raw menu rows into untouched RawDPL records (spec section 2)."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from .models import RawDPL


def _num(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_dispensary_platforms(csv_path: str | Path) -> dict[str, str]:
    """Map dispensary_id -> platform from the dispensary directory CSV."""
    out: dict[str, str] = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            store_id = (row.get("Platform Store ID") or "").strip()
            platform = (row.get("Platform") or "").strip()
            if store_id and platform:
                out[store_id] = platform
    return out


def raw_id(dispensary_id: str, product_id: str) -> str:
    base = f"{dispensary_id}:{product_id}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return f"raw_{digest}"


# backwards-compatible alias
_raw_id = raw_id


def load_raw_listings(
    json_path: str | Path,
    batch_id: str,
    platform_map: dict[str, str] | None = None,
) -> list[RawDPL]:
    """Load the source listings JSON into RawDPL records, preserving payload."""
    with open(json_path, encoding="utf-8") as fh:
        records = json.load(fh)
    return records_to_raw(records, batch_id, platform_map)


def records_to_raw(
    records: list[dict],
    batch_id: str,
    platform_map: dict[str, str] | None = None,
) -> list[RawDPL]:
    """Build RawDPL records from in-memory listing dicts, preserving payload."""
    platform_map = platform_map or {}
    out: list[RawDPL] = []
    for rec in records:
        dispensary_id = str(rec.get("dispensary_id", "")).strip()
        product_id = str(rec.get("product_id", "")).strip()
        out.append(
            RawDPL(
                raw_dpl_id=_raw_id(dispensary_id, product_id),
                batch_id=batch_id,
                source_dispensary=str(rec.get("dispensary", "")).strip(),
                source_dispensary_id=dispensary_id,
                source_platform=platform_map.get(dispensary_id),
                source_product_id=product_id,
                source_product_title=str(rec.get("title", "")).strip(),
                source_brand=(str(rec.get("brand", "")).strip() or None),
                source_category=(str(rec.get("category", "")).strip() or None),
                source_subcategory=(str(rec.get("original_subcategory", "")).strip() or None),
                price=_num(rec.get("price")),
                sale_price=None,
                thc_raw=(str(rec.get("thc", "")).strip() or None),
                thc_unit_raw=(str(rec.get("thc_unit", "")).strip() or None),
                cbd_raw=(str(rec.get("cbd", "")).strip() or None),
                cbd_unit_raw=(str(rec.get("cbd_unit", "")).strip() or None),
                weight_raw=(str(rec.get("weight", "")).strip() or None),
                strain_type_raw=(str(rec.get("strain_type", "")).strip() or None),
                image_url=(str(rec.get("image", "")).strip() or None),
                product_url=(str(rec.get("product_url", "")).strip() or None),
                raw_payload=rec,
            )
        )
    return out
