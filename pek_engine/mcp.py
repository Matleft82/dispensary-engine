"""Master Canonical Product creation + canonical title builder (spec section 21)."""

from __future__ import annotations

import hashlib

from .models import MCP, NormalizedDPL


def _mg_label(dpl: NormalizedDPL) -> str | None:
    if dpl.package_thc_mg:
        thc = dpl.package_thc_mg
        thc_s = f"{int(thc)}mg" if thc == int(thc) else f"{thc:g}mg"
        if dpl.package_cbd_mg:
            cbd = dpl.package_cbd_mg
            cbd_s = f"{int(cbd)}mg" if cbd == int(cbd) else f"{cbd:g}mg"
            return f"{thc_s} THC / {cbd_s} CBD"
        return f"{thc_s} THC"
    return None


def canonical_title(dpl: NormalizedDPL) -> str:
    """Brand + Size/MG/Count + Product + Modifier + Form (spec section 21)."""
    parts: list[str] = []
    if dpl.normalized_brand:
        parts.append(dpl.normalized_brand)

    cat = dpl.normalized_category
    if cat in ("Edibles", "Tinctures", "CBD"):
        mg = _mg_label(dpl)
        if mg:
            parts.append(mg)
        if dpl.ratio:
            parts.append(dpl.ratio)
    elif dpl.normalized_size:
        parts.append(dpl.normalized_size)

    if dpl.count and cat in ("Pre-Rolls", "Edibles", "Tinctures"):
        parts.append(f"{dpl.count}pk")

    if dpl.normalized_product_name:
        parts.append(dpl.normalized_product_name)

    # modifier: extract or infusion
    if dpl.extract_type and cat in ("Vapes", "Concentrates"):
        parts.append(dpl.extract_type)
    if dpl.infusion_type and dpl.infusion_type not in ("None", None) and cat == "Pre-Rolls":
        parts.append(dpl.infusion_type)

    # form tail
    form = dpl.subform or dpl.normalized_form
    if form and form not in parts:
        parts.append(form)

    title = " ".join(p for p in parts if p)
    return title.strip()


def mcp_id_for(pek: str) -> str:
    return "mcp_" + hashlib.sha1(pek.encode("utf-8")).hexdigest()[:16]


def build_mcp(pek: str, dpls: list[NormalizedDPL], now: str) -> MCP:
    """Create an MCP from the DPLs that share a PEK. Picks the richest DPL
    as the canonical representative."""
    rep = max(dpls, key=lambda d: (d.extraction_confidence,
                                    len(d.normalized_product_name or "")))
    dispensaries = {d.source_dispensary for d in dpls}
    image = next((d.image_url for d in dpls if d.image_url), None)

    avg_conf = sum(d.extraction_confidence for d in dpls) / len(dpls)
    needs_review = any("missing" in n for d in dpls for n in d.source_notes) \
        or avg_conf < 0.6
    review_status = "needs_review" if needs_review else "provisional"

    return MCP(
        mcp_id=mcp_id_for(pek),
        pek=pek,
        canonical_title=canonical_title(rep),
        search_title=rep.search_title,
        brand_id=rep.brand_id,
        normalized_brand=rep.normalized_brand or "",
        normalized_category=rep.normalized_category or "",
        normalized_form=rep.normalized_form,
        subform=rep.subform,
        canonical_product_name=rep.normalized_product_name or "",
        normalized_size=rep.normalized_size,
        unit_weight_grams=rep.unit_weight_grams,
        total_weight_grams=rep.total_weight_grams,
        count=rep.count,
        package_thc_mg=rep.package_thc_mg,
        package_cbd_mg=rep.package_cbd_mg,
        cannabinoid_profile=rep.cannabinoid_profile,
        ratio=rep.ratio,
        extract_type=rep.extract_type,
        infusion_type=rep.infusion_type,
        hardware_type=rep.hardware_type,
        dominance_or_type=rep.dominance_or_type,
        canonical_image_url=image,
        dpl_count=len(dpls),
        dispensary_count=len(dispensaries),
        review_status=review_status,
        created_at=now,
        updated_at=now,
    )
