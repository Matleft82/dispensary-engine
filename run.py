#!/usr/bin/env python3
"""CLI entry point for the dispensary engine.

Subcommands:
    normalize  raw listings -> MCPs + price index (default)
    scrape     harvest dispensary menus -> raw listings JSON
    agent      adjudicate engine outputs -> agent decisions (+ optional apply)

Examples:
    python run.py normalize --raw data/raw_listings.json --out outputs
    python run.py scrape --dispensaries data/dispensaries.csv --out data/raw_listings.json
    python run.py agent --out outputs --data data --apply
"""

from __future__ import annotations

import argparse
import json
import sys

from pek_engine.pipeline import run as run_normalize


def _cmd_normalize(args) -> None:
    summary = run_normalize(args.raw, args.brands, args.dispensaries, args.out,
                            args.batch_id)
    print(json.dumps(summary, indent=2))


def _cmd_scrape(args) -> None:
    from pek_engine.scrape import run_from_csv
    platforms = set(args.platforms.split(",")) if args.platforms else None
    result = run_from_csv(args.dispensaries, args.out, platforms=platforms,
                          limit=args.limit, batch_id=args.batch_id)
    print(json.dumps(result.to_dict(), indent=2))


def _cmd_agent(args) -> None:
    from pek_engine.agent import ProductAgent, summarize
    agent = ProductAgent()
    decisions = agent.adjudicate_outputs(args.out)
    from pathlib import Path
    Path(args.out, "agent_decisions.json").write_text(
        json.dumps([d.to_dict() for d in decisions], indent=1, ensure_ascii=False))
    summary = summarize(decisions)
    if args.apply:
        summary["applied"] = agent.apply(decisions, args.data)
    print(json.dumps(summary, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Dispensary price-comparison engine")
    sub = p.add_subparsers(dest="command")

    n = sub.add_parser("normalize", help="raw listings -> MCPs + price index")
    n.add_argument("--raw", default="data/raw_listings.json")
    n.add_argument("--brands", default="data/brand_aliases_seed.csv")
    n.add_argument("--dispensaries", default="data/dispensaries.csv")
    n.add_argument("--out", default="outputs")
    n.add_argument("--batch-id", default=None)
    n.set_defaults(func=_cmd_normalize)

    s = sub.add_parser("scrape", help="harvest dispensary menus -> raw listings")
    s.add_argument("--dispensaries", default="data/dispensaries.csv")
    s.add_argument("--out", default="data/raw_listings.json")
    s.add_argument("--platforms", default=None, help="comma list, e.g. dutchie,carrot")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--batch-id", default=None)
    s.set_defaults(func=_cmd_scrape)

    a = sub.add_parser("agent", help="adjudicate engine outputs into decisions")
    a.add_argument("--out", default="outputs")
    a.add_argument("--data", default="data")
    a.add_argument("--apply", action="store_true",
                   help="write auto-approved aliases/rejections to data tables")
    a.set_defaults(func=_cmd_agent)

    # default to `normalize` for backward compatibility
    argv = sys.argv[1:]
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["normalize"] + argv
    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
