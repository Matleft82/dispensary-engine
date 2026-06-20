"""Edible / tincture milligram normalization (spec section 12).

Edibles normalize by milligrams, count, and ratio — never by gram weight.
Dutchie ".1g"/".01g" gram artifacts are ignored (handled by not passing
weight into edible sizing).
"""

from __future__ import annotations

import re

from .size import parse_count

# NY adult-use validation ceiling (spec section 12) — used only to sanity check.
NY_PACKAGE_THC_CEILING = 100.0


def _cannabinoid_mgs(text: str) -> dict[str, float]:
    """Find explicit '<n>mg <cannabinoid>' / '<cannabinoid> <n>mg' values."""
    out: dict[str, float] = {}
    for cann in ("thc", "cbd", "cbn", "cbg", "cbc"):
        m = re.search(rf"(\d+(?:\.\d+)?)\s*mg\s*{cann}\b", text)
        if not m:
            m = re.search(rf"\b{cann}\s*:?\s*(\d+(?:\.\d+)?)\s*mg", text)
        if m:
            out[cann] = float(m.group(1))
    return out


def _ratio(text: str, strain_type_raw: str | None) -> str | None:
    m = re.search(r"\b(\d+)\s*:\s*(\d+)\b", text)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    s = (strain_type_raw or "").lower()
    m = re.search(r"(\d+)\s*to\s*(\d+)", s)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return None


def resolve_edible(search_title: str, thc_raw: str | None, thc_unit: str | None,
                   cbd_raw: str | None, cbd_unit: str | None,
                   strain_type_raw: str | None) -> dict:
    """Resolve package/serving mg, ratio, cannabinoid profile, and count."""
    t = (search_title or "").lower()
    count = parse_count(t)

    # "10x10mg" / "10 x 10 mg" -> count x serving
    serving_thc = None
    m = re.search(r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*mg", t)
    if m:
        count = count or int(m.group(1))
        serving_thc = float(m.group(2))

    explicit = _cannabinoid_mgs(t)
    package_thc = explicit.get("thc")
    package_cbd = explicit.get("cbd")

    # generic "100mg" with no cannabinoid label -> assume THC package total
    if package_thc is None:
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*mg\b", t)
        if m:
            package_thc = float(m.group(1))

    # field fallbacks (only when unit is milligrams)
    def _num(v):
        try:
            return float(str(v).strip())
        except (TypeError, ValueError):
            return None

    if package_thc is None and (thc_unit or "").upper() == "MILLIGRAMS":
        package_thc = _num(thc_raw)
    if package_cbd is None and (cbd_unit or "").upper() == "MILLIGRAMS":
        package_cbd = _num(cbd_raw)

    # reconcile serving/package with count
    if serving_thc is not None and package_thc is None and count:
        package_thc = round(serving_thc * count, 2)
    if serving_thc is None and package_thc is not None and count:
        serving_thc = round(package_thc / count, 2)

    serving_cbd = None
    if package_cbd is not None and count:
        serving_cbd = round(package_cbd / count, 2)

    ratio = _ratio(t, strain_type_raw)

    profile_parts = []
    if package_thc:
        profile_parts.append("THC")
    if package_cbd:
        profile_parts.append("CBD")
    for cann in ("cbn", "cbg", "cbc"):
        if explicit.get(cann):
            profile_parts.append(cann.upper())
    cannabinoid_profile = "/".join(profile_parts) if profile_parts else None

    return {
        "package_thc_mg": package_thc,
        "serving_thc_mg": serving_thc,
        "package_cbd_mg": package_cbd,
        "serving_cbd_mg": serving_cbd,
        "cannabinoid_profile": cannabinoid_profile,
        "ratio": ratio,
        "count": count,
    }
