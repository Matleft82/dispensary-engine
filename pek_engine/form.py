"""Form, subform, and hardware normalization (spec sections 6, 15)."""

from __future__ import annotations

from . import rules


def _first_match(text: str, patterns) -> str | None:
    for canonical, keywords in patterns:
        for kw in keywords:
            if kw in text:
                return canonical
    return None


def detect_hardware(text: str) -> str | None:
    """Vape hardware type (spec section 15)."""
    return _first_match(text, rules.HARDWARE_PATTERNS)


def resolve_form(category: str | None, search_text: str,
                 sub_text: str) -> tuple[str | None, str | None, str | None]:
    """Return (normalized_form, subform, hardware_type) for a category.

    search_text/sub_text are lowercased title and subcategory strings.
    """
    text = f"{search_text} {sub_text}".strip()

    if category == "Vapes":
        hardware = detect_hardware(text) or "Unknown"
        form_by_hw = {
            "AIO": "AIO Disposable Vape",
            "Disposable": "Disposable Vape",
            "Pod": "Vape Pod",
            "510 Cartridge": "Vape Cartridge",
            "Unknown": "Vape",
        }
        return form_by_hw.get(hardware, "Vape"), None, hardware

    if category == "Flower":
        subform = _first_match(text, rules.FLOWER_SUBFORMS)
        return (subform or "Whole Flower"), subform, None

    if category == "Pre-Rolls":
        subform = _first_match(text, rules.PREROLL_SUBFORMS)
        return "Pre-Roll", subform, None

    if category == "Concentrates":
        if "syringe" in text or "dablicator" in text or "applicator" in text:
            return "Concentrate", "Syringe", None
        return "Concentrate", None, None

    if category == "Edibles":
        form = _first_match(text, rules.EDIBLE_FORM_PATTERNS)
        return (form or "Edible"), None, None

    if category == "Tinctures":
        return "Tincture", None, None

    if category == "Topicals":
        return "Topical", None, None

    if category == "CBD":
        form = _first_match(text, rules.EDIBLE_FORM_PATTERNS)
        return (form or "CBD"), None, None

    return None, None, None
