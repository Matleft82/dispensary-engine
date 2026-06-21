"""End-to-end pipeline (spec section 27): raw menus -> MCPs + price index."""

from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from . import matching
from .brand import BrandResolver
from .ingest import (load_dispensary_platforms, load_raw_listings, raw_id,
                     records_to_raw)
from .models import ELIGIBLE, NormalizedDPL, PriceIndexRow
from .normalize import normalize_dpl


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(path: Path, rows) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, ensure_ascii=False)


def run(raw_json: str, brand_csv: str, dispensary_csv: str,
        out_dir: str, batch_id: str | None = None) -> dict:
    batch_id = batch_id or f"batch_{date.today().isoformat()}_{uuid.uuid4().hex[:6]}"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = _now_iso()

    platforms = load_dispensary_platforms(dispensary_csv)
    raws = load_raw_listings(raw_json, batch_id, platforms)
    resolver = BrandResolver.from_seed_csv(brand_csv)

    normalized: list[NormalizedDPL] = [normalize_dpl(r, resolver) for r in raws]
    return _finalize(normalized, resolver, batch_id, now, out)


def run_incremental(prev_out_dir: str, delta_json: str, brand_csv: str,
                    dispensary_csv: str, out_dir: str,
                    batch_id: str | None = None) -> dict:
    """Update the previous batch using only the harvested delta: re-normalize
    added/changed listings, drop removed ones, carry unchanged ones forward, then
    rebuild MCPs + price index. Unchanged listings are never re-normalized."""
    batch_id = batch_id or f"batch_{date.today().isoformat()}_{uuid.uuid4().hex[:6]}"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = _now_iso()

    platforms = load_dispensary_platforms(dispensary_csv)
    resolver = BrandResolver.from_seed_csv(brand_csv)

    prev_path = Path(prev_out_dir) / "normalized_dpls.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else []
    by_id: dict[str, NormalizedDPL] = {
        d["raw_dpl_id"]: NormalizedDPL.from_dict(d) for d in prev}

    delta = json.loads(Path(delta_json).read_text())
    changed_rows = delta.get("changed_listings", [])
    removed = delta.get("removed_product_ids", [])

    for rm in removed:
        disp = rm.get("dispensary_id", "") if isinstance(rm, dict) else ""
        pid = rm.get("product_id", "") if isinstance(rm, dict) else str(rm)
        by_id.pop(raw_id(disp, pid), None)

    raws = records_to_raw(changed_rows, batch_id, platforms)
    for r in raws:
        by_id[r.raw_dpl_id] = normalize_dpl(r, resolver)

    normalized = list(by_id.values())
    summary = _finalize(normalized, resolver, batch_id, now, out)
    summary["incremental"] = {"re_normalized": len(raws), "removed": len(removed),
                              "carried_forward": len(prev) - len(removed)}
    return summary


def _finalize(normalized: list[NormalizedDPL], resolver: BrandResolver,
              batch_id: str, now: str, out: Path) -> dict:
    eligible = [d for d in normalized if d.comparison_status == ELIGIBLE
                and d.proposed_pek]

    mcps, links, by_pek = matching.build_mcps(eligible, batch_id, now)

    # representative DPL per MCP (richest one) for review comparisons
    rep_dpl: dict[str, NormalizedDPL] = {}
    mcp_by_id = {m.mcp_id: m for m in mcps}
    for m in mcps:
        dpls = by_pek[m.pek]
        rep_dpl[m.mcp_id] = max(
            dpls, key=lambda d: (d.extraction_confidence,
                                 len(d.normalized_product_name or "")))

    reviews, rejected, product_alias_suggestions = matching.analyze_near_matches(
        mcps, rep_dpl, batch_id)
    dq_flags = matching.data_quality_flags(normalized, batch_id)

    # --- price comparison index ---
    dpl_by_id = {d.dpl_id: d for d in normalized}
    link_by_dpl = {l.dpl_id: l for l in links}
    price_index: list[PriceIndexRow] = []
    for link in links:
        d = dpl_by_id[link.dpl_id]
        m = mcp_by_id[link.mcp_id]
        if d.effective_price is None:
            continue
        price_index.append(PriceIndexRow(
            price_index_id="px_" + uuid.uuid4().hex[:16],
            mcp_id=m.mcp_id, dpl_id=d.dpl_id,
            source_dispensary=d.source_dispensary,
            source_platform=d.source_platform,
            canonical_title=m.canonical_title,
            normalized_brand=m.normalized_brand,
            normalized_category=m.normalized_category,
            normalized_form=m.normalized_form,
            normalized_size=m.normalized_size,
            price=d.price, sale_price=d.sale_price,
            effective_price=d.effective_price,
            product_url=d.product_url, image_url=d.image_url,
            in_stock=None))

    # --- write outputs ---
    _dump(out / "normalized_dpls.json", [d.to_dict() for d in normalized])
    _dump(out / "master_canonical_products.json", [m.to_dict() for m in mcps])
    _dump(out / "mcp_dpl_links.json", [l.to_dict() for l in links])
    _dump(out / "price_comparison_index.json", [p.to_dict() for p in price_index])
    _dump(out / "review_queue.json", [r.to_dict() for r in reviews])
    _dump(out / "rejected_near_matches.json", rejected)
    _dump(out / "data_quality_flags.json", [f.to_dict() for f in dq_flags])
    _dump(out / "brand_alias_suggestions.json", list(resolver.suggestions.values()))
    _dump(out / "product_alias_suggestions.json", list(product_alias_suggestions.values()))

    summary = _summary(normalized, eligible, mcps, links, reviews, rejected,
                       resolver, product_alias_suggestions, dq_flags, price_index,
                       batch_id, now)
    _dump(out / "batch_summary.json", summary)
    (out / "batch_summary.md").write_text(_summary_md(summary, mcps, reviews,
                                                       rep_dpl, mcp_by_id),
                                          encoding="utf-8")
    return summary


def _summary(normalized, eligible, mcps, links, reviews, rejected, resolver,
             product_aliases, dq_flags, price_index, batch_id, now) -> dict:
    multi = [m for m in mcps if m.dispensary_count > 1]
    cat_counts = Counter(d.normalized_category for d in eligible)
    excluded = Counter(d.comparison_status for d in normalized
                       if d.comparison_status != ELIGIBLE)
    return {
        "batch_id": batch_id,
        "generated": now,
        "menus_processed": len({d.source_dispensary for d in normalized}),
        "raw_dpls_imported": len(normalized),
        "eligible_cannabis_dpls": len(eligible),
        "excluded_dpls": dict(excluded),
        "new_mcps_created": len(mcps),
        "mcps_at_multiple_dispensaries": len(multi),
        "dpls_linked": len(links),
        "candidate_review_items": len(reviews),
        "rejected_near_matches": len(rejected),
        "brand_alias_suggestions": len(resolver.suggestions),
        "product_alias_suggestions": len(product_aliases),
        "data_quality_flags": len(dq_flags),
        "price_index_rows": len(price_index),
        "category_counts": dict(cat_counts),
        "review_issue_breakdown": dict(Counter(r.issue_type for r in reviews)),
        "dq_flag_breakdown": dict(Counter(f.problem_type for f in dq_flags)),
    }


def _summary_md(s: dict, mcps, reviews, rep_dpl, mcp_by_id) -> str:
    lines = ["# Batch Summary", ""]
    lines.append(f"- Batch: `{s['batch_id']}`  ")
    lines.append(f"- Menus processed: {s['menus_processed']}")
    lines.append(f"- Raw DPLs imported: {s['raw_dpls_imported']}")
    lines.append(f"- Eligible cannabis DPLs: {s['eligible_cannabis_dpls']}")
    lines.append(f"- New MCPs created: {s['new_mcps_created']}")
    lines.append(f"- MCPs sold at multiple dispensaries: {s['mcps_at_multiple_dispensaries']}")
    lines.append(f"- DPLs linked to MCPs: {s['dpls_linked']}")
    lines.append(f"- Candidate review items: {s['candidate_review_items']}")
    lines.append(f"- Rejected near-matches: {s['rejected_near_matches']}")
    lines.append(f"- Brand alias suggestions: {s['brand_alias_suggestions']}")
    lines.append(f"- Product alias suggestions: {s['product_alias_suggestions']}")
    lines.append(f"- Data quality flags: {s['data_quality_flags']}")
    lines.append(f"- Price index rows: {s['price_index_rows']}")
    lines.append("")
    lines.append("## Category counts (eligible)")
    for k, v in sorted(s["category_counts"].items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Top multi-dispensary products (price comparison candidates)")
    top = sorted(mcps, key=lambda m: m.dispensary_count, reverse=True)[:25]
    for m in top:
        if m.dispensary_count < 2:
            continue
        lines.append(f"- **{m.canonical_title}** — {m.dispensary_count} dispensaries, "
                     f"{m.dpl_count} listings  \n  `{m.pek}`")
    lines.append("")
    lines.append("## Review queue (sample)")
    for r in reviews[:25]:
        lines.append(f"- [{r.risk_level}] {r.issue_type}: {r.reason_for_review} "
                     f"→ {r.recommended_action}")
        for t in r.source_titles_compared:
            lines.append(f"    - {t}")
    return "\n".join(lines) + "\n"
