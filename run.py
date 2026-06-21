#!/usr/bin/env python3
"""CLI entry point for the dispensary engine.

Subcommands:
    normalize  raw listings -> MCPs + price index (default)
    scrape     harvest dispensary menus -> raw listings JSON (--incremental for deltas)
    agent      adjudicate engine outputs -> agent decisions (+ optional apply)
    archive    fold price events into daily/monthly rollups + compact retention

Examples:
    python run.py normalize --raw data/raw_listings.json --out outputs
    python run.py scrape --dispensaries data/dispensaries.csv --out data/raw_listings.json
    python run.py scrape --incremental --state-dir state --delta data/delta.json --out data/raw_listings.json
    python run.py normalize --incremental --prev outputs --delta data/delta.json --out outputs
    python run.py agent --out outputs --data data --apply
    python run.py archive --out outputs --archive-dir archive
"""

from __future__ import annotations

import argparse
import json
import sys

from pek_engine.pipeline import run as run_normalize
from pek_engine.pipeline import run_incremental as run_normalize_incremental


def _cmd_normalize(args) -> None:
    if getattr(args, "incremental", False):
        summary = run_normalize_incremental(
            args.prev, args.delta, args.brands, args.dispensaries, args.out,
            args.batch_id)
    else:
        summary = run_normalize(args.raw, args.brands, args.dispensaries, args.out,
                                args.batch_id)
    print(json.dumps(summary, indent=2))


def _cmd_scrape(args) -> None:
    from pek_engine.scrape import run_from_csv
    platforms = set(args.platforms.split(",")) if args.platforms else None
    result = run_from_csv(
        args.dispensaries, args.out, platforms=platforms, limit=args.limit,
        batch_id=args.batch_id, incremental=args.incremental,
        state_dir=args.state_dir, delta_json=args.delta,
        price_history=args.price_history)
    print(json.dumps(result.to_dict(), indent=2))


def _cmd_archive(args) -> None:
    import shutil
    from pathlib import Path

    from pek_engine import analytics
    events = analytics.load_jsonl(args.price_history)
    Path(args.archive_dir).mkdir(parents=True, exist_ok=True)
    if args.out and events:
        events = analytics.enrich_events_with_mcp(events, args.out)
        analytics.write_jsonl(args.price_history, events)
        analytics.write_jsonl(Path(args.archive_dir) / "current_state.jsonl",
                              analytics.build_current_state(args.out))
    dst = Path(args.archive_dir) / "price_history.jsonl"
    if Path(args.price_history).resolve() != dst.resolve():
        shutil.copy(args.price_history, dst)
    stats = analytics.compact(args.archive_dir, recent_days=args.recent_days,
                              daily_months=args.daily_months)
    print(json.dumps(stats, indent=2))


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
    n.add_argument("--incremental", action="store_true",
                   help="update --prev outputs using only --delta changes")
    n.add_argument("--prev", default="outputs", help="previous batch output dir")
    n.add_argument("--delta", default="data/delta.json", help="delta JSON from scrape")
    n.set_defaults(func=_cmd_normalize)

    s = sub.add_parser("scrape", help="harvest dispensary menus -> raw listings")
    s.add_argument("--dispensaries", default="data/dispensaries.csv")
    s.add_argument("--out", default="data/raw_listings.json")
    s.add_argument("--platforms", default=None, help="comma list, e.g. dutchie,carrot")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--batch-id", default=None)
    s.add_argument("--incremental", action="store_true",
                   help="diff against last pull; only changes flow downstream")
    s.add_argument("--state-dir", default="state", help="per-dispensary snapshots")
    s.add_argument("--delta", default=None, help="write changed/removed to this file")
    s.add_argument("--price-history", default=None, help="append price events here")
    s.set_defaults(func=_cmd_scrape)

    a = sub.add_parser("agent", help="adjudicate engine outputs into decisions")
    a.add_argument("--out", default="outputs")
    a.add_argument("--data", default="data")
    a.add_argument("--apply", action="store_true",
                   help="write auto-approved aliases/rejections to data tables")
    a.set_defaults(func=_cmd_agent)

    ar = sub.add_parser("archive", help="fold price events into rollups + compact")
    ar.add_argument("--out", default="outputs",
                    help="batch output dir (to map events -> MCP ids); optional")
    ar.add_argument("--archive-dir", default="archive")
    ar.add_argument("--price-history", default="outputs/price_history.jsonl")
    ar.add_argument("--recent-days", type=int, default=90)
    ar.add_argument("--daily-months", type=int, default=13)
    ar.set_defaults(func=_cmd_archive)

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
