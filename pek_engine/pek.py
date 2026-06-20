"""Product Equality Key generation (spec sections 1, 18).

The PEK is a deterministic, explainable fingerprint of the sellable product.
Blank fields stay blank — facts are never fabricated.
"""

from __future__ import annotations

from .text_clean import normalize_key_token as tok


def _mg(value) -> str:
    if value is None:
        return ""
    if float(value) == int(value):
        return f"{int(value)}mg"
    return f"{value:g}mg"


def build_pek(dpl: dict) -> tuple[str, dict]:
    """Build (pek_string, components) for an eligible cannabis DPL dict.

    `dpl` is a mapping with the normalized fields produced by the pipeline.
    """
    category = dpl.get("normalized_category")
    brand = tok(dpl.get("normalized_brand") or "")
    product = tok(dpl.get("normalized_product_name") or "")
    form = tok(dpl.get("normalized_form") or "")
    subform = tok(dpl.get("subform") or "")
    hardware = tok(dpl.get("hardware_type") or "")
    extract = tok(dpl.get("extract_type") or "")
    infusion = tok(dpl.get("infusion_type") or "")
    count = str(dpl.get("count")) if dpl.get("count") else ""
    profile = tok(dpl.get("cannabinoid_profile") or "")
    ratio = tok(dpl.get("ratio") or "")
    size = tok(dpl.get("normalized_size") or "")
    cat = tok(category or "")

    components: dict[str, str] = {}
    parts: list[str]

    if category == "Flower":
        components = {"brand": brand, "category": cat, "subform": subform,
                      "size": size, "product": product}
        parts = [brand, cat, subform, size, product]

    elif category == "Pre-Rolls":
        components = {"brand": brand, "category": cat, "form": form,
                      "subform": subform, "size": size, "count": count,
                      "product": product, "infusion": infusion}
        parts = [brand, cat, form, subform, size, count, product, infusion]

    elif category == "Vapes":
        components = {"brand": brand, "category": cat, "form": form,
                      "hardware": hardware, "size": size, "product": product,
                      "extract": extract}
        parts = [brand, cat, form, hardware, size, product, extract]

    elif category == "Concentrates":
        components = {"brand": brand, "category": cat, "size": size,
                      "product": product, "extract": extract, "subform": subform}
        parts = [brand, cat, size, product, extract, subform]

    elif category == "Edibles":
        pkg = _mg(dpl.get("package_thc_mg"))
        components = {"brand": brand, "category": cat, "form": form,
                      "product": product, "package_mg": pkg, "count": count,
                      "profile": profile, "ratio": ratio}
        parts = [brand, cat, form, product, pkg, count, profile, ratio]

    elif category == "Tinctures":
        pkg = _mg(dpl.get("package_thc_mg"))
        components = {"brand": brand, "category": cat, "product": product,
                      "package_mg": pkg, "ratio": ratio, "profile": profile}
        parts = [brand, cat, "tincture", product, pkg, ratio, profile]

    elif category == "Topicals":
        components = {"brand": brand, "category": cat, "product": product,
                      "size": size}
        parts = [brand, cat, "topical", product, size]

    else:  # CBD / fallback — general PEK
        pkg = _mg(dpl.get("package_thc_mg"))
        components = {"brand": brand, "category": cat, "form": form,
                      "product": product, "size": size, "package_mg": pkg}
        parts = [brand, cat, form, product, size, pkg]

    pek = "|".join(parts)
    return pek, components
