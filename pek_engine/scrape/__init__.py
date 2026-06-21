"""Scraper engine: multi-platform dispensary menu harvesting.

Harvested rows use the canonical raw-listing schema that feeds the normalization
engine, so scrape -> normalize is one continuous pipeline.
"""

from .adapters import ADAPTERS
from .delta import Delta, MenuStateStore, diff
from .http import FixtureClient, HttpClient
from .registry import DispensaryEntry, load_registry
from .runner import HarvestResult, harvest, new_batch_id, run_from_csv
from .sinks import DeltaSink, JsonSink, PostgresSink

__all__ = [
    "ADAPTERS", "FixtureClient", "HttpClient", "DispensaryEntry",
    "load_registry", "HarvestResult", "harvest", "new_batch_id",
    "run_from_csv", "JsonSink", "PostgresSink", "DeltaSink",
    "Delta", "MenuStateStore", "diff",
]
