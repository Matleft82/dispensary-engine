#!/usr/bin/env python3
"""CLI entry point for the PEK/MCP normalization engine.

Usage:
    python run.py \
        --raw data/raw_listings.json \
        --brands data/brand_aliases_seed.csv \
        --dispensaries data/dispensaries.csv \
        --out outputs
"""

from __future__ import annotations

import argparse
import json

from pek_engine.pipeline import run


def main() -> None:
    p = argparse.ArgumentParser(description="PEK/MCP normalization engine")
    p.add_argument("--raw", default="data/raw_listings.json")
    p.add_argument("--brands", default="data/brand_aliases_seed.csv")
    p.add_argument("--dispensaries", default="data/dispensaries.csv")
    p.add_argument("--out", default="outputs")
    p.add_argument("--batch-id", default=None)
    args = p.parse_args()

    summary = run(args.raw, args.brands, args.dispensaries, args.out, args.batch_id)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
