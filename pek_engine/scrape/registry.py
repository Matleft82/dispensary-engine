"""Dispensary registry: load store -> (platform, external_id, menu_url)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

# Normalize the CSV's platform spelling to the adapter key.
PLATFORM_ALIASES = {
    "dutchie": "dutchie",
    "carrot": "carrot",
    "jane": "jane",
    "iheartjane": "jane",
    "blaze": "blaze",
    "weedmaps": "weedmaps",
    "aiq": "dispense",
    "dispense": "dispense",
    "proteus420": "proteus",
    "proteus": "proteus",
    "treez": "treez",
    "flowhub": "flowhub",
    "kushmart": "kushmart",
    "custom": "kushmart",  # the 3 "Custom" stores in this registry are KushMart
}


@dataclass
class DispensaryEntry:
    name: str
    platform: str          # adapter key (normalized)
    raw_platform: str      # as written in the CSV
    external_id: str       # platform-specific id (may be blank -> not runnable)
    menu_url: str
    website: str

    @property
    def runnable(self) -> bool:
        return bool(self.platform) and bool(self.external_id)


def load_registry(csv_path: str | Path) -> list[DispensaryEntry]:
    entries: list[DispensaryEntry] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            raw_platform = (row.get("Platform") or "").strip()
            platform = PLATFORM_ALIASES.get(raw_platform.lower(), raw_platform.lower())
            entries.append(DispensaryEntry(
                name=(row.get("Dispensary") or "").strip().strip('",'),
                platform=platform,
                raw_platform=raw_platform,
                external_id=(row.get("Platform Store ID") or "").strip(),
                menu_url=(row.get("Menu URL") or "").strip(),
                website=(row.get("Website") or "").strip(),
            ))
    return entries
