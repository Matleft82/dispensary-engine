"""Per-listing normalization: RawDPL -> NormalizedDPL (spec sections 3-18)."""

from __future__ import annotations

from . import (
    category as category_mod,
    edible_mg,
    eligibility,
    extract_infusion,
    form as form_mod,
    pek as pek_mod,
    product_name,
    rules,
    size as size_mod,
    text_clean,
)
from .brand import BrandResolver
from .models import ELIGIBLE, NormalizedDPL, RawDPL


def _normalize_dominance(strain_type_raw: str | None) -> tuple[str, str | None]:
    raw = (strain_type_raw or "").strip()
    key = raw.lower()
    return rules.DOMINANCE_MAP.get(key, "Unknown" if not raw else "Unknown"), (raw or None)


def _resolve_brand(raw: RawDPL, search_title: str, resolver: BrandResolver) -> dict:
    info = resolver.resolve(raw.source_brand)
    if info["known"] or raw.source_brand:
        if not info["known"] and raw.source_brand:
            resolver.add_suggestion_example(raw.source_brand, raw.source_product_title)
        return info

    # blank brand -> try title-prefix / suffix extraction against known brands
    segs = text_clean.segments(raw.source_product_title)
    for seg in ([segs[0], segs[-1]] if segs else []):
        hit = resolver.lookup_known(seg)
        if hit:
            canonical, brand_id = hit
            return {"normalized_brand": canonical, "brand_id": brand_id,
                    "brand_confidence": 0.8, "alias_type": "title_prefix",
                    "known": True}
    return info  # still unresolved (blank)


def normalize_dpl(raw: RawDPL, resolver: BrandResolver) -> NormalizedDPL:
    display = text_clean.display_title(raw.source_product_title)
    search = text_clean.search_title(raw.source_product_title)
    sub = (raw.source_subcategory or "").lower()
    combined = f"{search} {sub}"

    notes: list[str] = []
    comparison_status = eligibility.classify(
        raw.source_category, raw.source_subcategory, raw.source_product_title)

    brand_info = _resolve_brand(raw, search, resolver)
    dominance, strain_reported = _normalize_dominance(raw.strain_type_raw)
    effective_price = raw.sale_price if raw.sale_price is not None else raw.price

    base = dict(
        dpl_id="dpl_" + raw.raw_dpl_id.removeprefix("raw_"),
        raw_dpl_id=raw.raw_dpl_id,
        batch_id=raw.batch_id,
        source_dispensary=raw.source_dispensary,
        source_dispensary_id=raw.source_dispensary_id,
        source_platform=raw.source_platform,
        source_product_id=raw.source_product_id,
        source_product_title=raw.source_product_title,
        display_title=display,
        search_title=search,
        source_brand=raw.source_brand,
        normalized_brand=brand_info["normalized_brand"],
        brand_id=brand_info["brand_id"],
        brand_confidence=brand_info["brand_confidence"],
        raw_category=raw.source_category,
        raw_subcategory=raw.source_subcategory,
        normalized_category=None, normalized_form=None, subform=None,
        hardware_type=None, product_name_raw=None, normalized_product_name=None,
        size_value=None, size_unit=None, normalized_size=None,
        unit_weight_grams=None, total_weight_grams=None, count=None,
        package_thc_mg=None, serving_thc_mg=None, package_cbd_mg=None,
        serving_cbd_mg=None, cannabinoid_profile=None, ratio=None,
        extract_type=None, infusion_type=None,
        dominance_or_type=dominance, strain_type_reported=strain_reported,
        thc_value=raw.thc_raw, cbd_value=raw.cbd_raw,
        price=raw.price, sale_price=raw.sale_price, effective_price=effective_price,
        image_url=raw.image_url, product_url=raw.product_url,
        comparison_status=comparison_status, proposed_pek=None,
        pek_components={}, extraction_confidence=0.0, source_notes=notes,
    )

    if comparison_status != ELIGIBLE:
        return NormalizedDPL(**base)

    # --- category / form ---
    cat, cat_evidence = category_mod.canonical_category(
        raw.source_category, raw.source_subcategory, raw.source_product_title)
    base["normalized_category"] = cat
    if not cat:
        notes.append("unmapped_category")

    form, subform, hardware = form_mod.resolve_form(cat, search, sub)
    base["normalized_form"] = form
    base["subform"] = subform
    base["hardware_type"] = hardware

    # --- extract / infusion ---
    extract = extract_infusion.resolve_extract(cat, combined)
    infusion = extract_infusion.resolve_infusion(cat, combined)
    base["extract_type"] = extract
    base["infusion_type"] = infusion
    if cat == "Concentrates":
        base["subform"] = extract_infusion.concentrate_subform(extract, subform)

    # --- size / potency ---
    if cat in ("Edibles", "Tinctures", "CBD"):
        mg = edible_mg.resolve_edible(
            search, raw.thc_raw, raw.thc_unit_raw, raw.cbd_raw,
            raw.cbd_unit_raw, raw.strain_type_raw)
        base.update({k: mg[k] for k in (
            "package_thc_mg", "serving_thc_mg", "package_cbd_mg",
            "serving_cbd_mg", "cannabinoid_profile", "ratio", "count")})
        if mg["package_thc_mg"] is None and mg["package_cbd_mg"] is None:
            notes.append("missing_mg")
    else:
        sz = size_mod.resolve_size(cat, search, raw.weight_raw)
        base.update({
            "size_value": sz["size_value"], "size_unit": sz["size_unit"],
            "normalized_size": sz["normalized_size"],
            "unit_weight_grams": sz["unit_weight_grams"],
            "total_weight_grams": sz["total_weight_grams"], "count": sz["count"]})
        if sz["normalized_size"] is None and cat != "Pre-Rolls":
            notes.append("missing_size")

    # --- product identity ---
    name, name_conf = product_name.extract_product_name(
        search, raw.source_brand, brand_info["normalized_brand"])
    base["product_name_raw"] = name
    base["normalized_product_name"] = name
    if not name:
        notes.append("missing_product_identity")

    # --- confidence aggregate ---
    conf = min(brand_info["brand_confidence"], name_conf)
    if cat in ("Vapes", "Concentrates") and not extract:
        notes.append("missing_extract_type")
        conf = min(conf, 0.5)
    base["extraction_confidence"] = round(conf, 2)

    ndpl = NormalizedDPL(**base)

    # --- PEK ---
    pek, comps = pek_mod.build_pek(ndpl.to_dict())
    ndpl.proposed_pek = pek
    ndpl.pek_components = comps
    return ndpl
