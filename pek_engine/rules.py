"""Editable lookup tables for normalization.

Keep domain knowledge here (not in logic) so the engine can grow without code
changes. Everything is matched against lowercased, separator-cleaned text.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical categories (spec section 29 — minimal category philosophy)
# ---------------------------------------------------------------------------
CATEGORIES = [
    "Flower",
    "Pre-Rolls",
    "Vapes",
    "Concentrates",
    "Edibles",
    "Topicals",
    "Tinctures",
    "CBD",
]

# Raw source category/subcategory string -> canonical category.
# Matched after lowercasing. Longest / most specific keys win.
CATEGORY_MAP = {
    "pre-rolls": "Pre-Rolls",
    "pre rolls": "Pre-Rolls",
    "preroll": "Pre-Rolls",
    "prerolls": "Pre-Rolls",
    "pre-roll": "Pre-Rolls",
    "joint": "Pre-Rolls",
    "blunt": "Pre-Rolls",
    "flower": "Flower",
    "bud": "Flower",
    "vaporizers": "Vapes",
    "vaporizer": "Vapes",
    "vapes": "Vapes",
    "vape": "Vapes",
    "carts": "Vapes",
    "cart": "Vapes",
    "cartridge": "Vapes",
    "cartridges": "Vapes",
    "disposables": "Vapes",
    "disposable": "Vapes",
    "concentrates": "Concentrates",
    "concentrate": "Concentrates",
    "dabs": "Concentrates",
    "extracts": "Concentrates",
    "edibles": "Edibles",
    "edible": "Edibles",
    "beverages": "Edibles",
    "beverage": "Edibles",
    "drinks": "Edibles",
    "tinctures": "Tinctures",
    "tincture": "Tinctures",
    "topicals": "Topicals",
    "topical": "Topicals",
    "cbd": "CBD",
}

# ---------------------------------------------------------------------------
# Non-cannabis exclusion (spec section 4)
# ---------------------------------------------------------------------------
EXCLUDED_CATEGORY_KEYWORDS = {
    "accessories": "excluded_accessory",
    "accessory": "excluded_accessory",
    "merch": "excluded_merchandise",
    "merchandise": "excluded_merchandise",
    "apparel": "excluded_merchandise",
}

EXCLUDED_TITLE_KEYWORDS = [
    "rolling paper", "rolling papers", "grinder", "battery", "batteries",
    "charger", "lighter", "torch", "ashtray", "stash jar", "dab tool",
    "rolling tray", "cones", "raw cone", "papers", "hoodie", "t-shirt",
    "tshirt", "sticker", "hat", "beanie", "keychain", "glassware", "bong",
    "pipe", "dab rig", "rig", "downstem", "banger",
]

# Menu decoration noise to strip from titles (spec section 3)
DECORATION_TOKENS = [
    "sale", "new", "staff pick", "best seller", "bestseller", "limited",
    "bogo", "online only", "vendor day", "fresh drop", "featured",
    "clearance", "deal", "special",
]

# ---------------------------------------------------------------------------
# Form / subform / hardware (spec sections 6, 15)
# ---------------------------------------------------------------------------
# Vape hardware — order matters (most specific first).
HARDWARE_PATTERNS = [
    ("AIO", ["all-in-one", "all in one", "all in ones", "aio"]),
    ("Pod", ["pax pod", "live pod", "pod"]),
    ("Disposable", ["disposable", "dispo"]),
    ("510 Cartridge", ["510 cart", "510 cartridge", "510", "cartridge", "carts", "cart"]),
]

# Concentrate / flower / preroll subforms
FLOWER_SUBFORMS = [
    ("Small Buds", ["small buds", "smalls", "popcorn", "small bud"]),
    ("Shake", ["shake", "trim", "shake/trim", "shake-trim"]),
    ("Ground Flower", ["ground flower", "milled"]),
    ("Whole Flower", ["whole flower", "whole-flower"]),
]

PREROLL_SUBFORMS = [
    ("Hash Hole", ["hash hole", "hash-hole", "hashhole", "donut", "donuts"]),
    ("Blunt", ["blunt", "blunts"]),
    ("Joint", ["joint"]),
]

# ---------------------------------------------------------------------------
# Extract type (spec section 13) — order matters (most specific first)
# ---------------------------------------------------------------------------
EXTRACT_PATTERNS = [
    ("Liquid Diamonds", ["liquid diamonds", "liquid diamond"]),
    ("Live Resin", ["live resin", "live-resin"]),
    ("Cured Resin", ["cured resin", "cured-resin"]),
    ("Live Rosin", ["live rosin", "live-rosin"]),
    ("Rosin", ["rosin"]),
    ("Resin", ["resin"]),
    ("Distillate", ["distillate", "distalate", "disty"]),
    ("Diamonds", ["diamonds", "diamond"]),
    ("Sauce", ["sauce"]),
    ("Badder", ["badder", "batter"]),
    ("Budder", ["budder"]),
    ("Crumble", ["crumble"]),
    ("Shatter", ["shatter"]),
    ("Bubble Hash", ["bubble hash", "ice water hash"]),
    ("Kief", ["kief"]),
    ("Hash", ["hash"]),
    ("RSO", ["rso"]),
    ("Wax", ["wax"]),
]

# Extract types that double as concentrate forms.
CONCENTRATE_FORM_FROM_EXTRACT = {
    "Badder", "Budder", "Crumble", "Shatter", "Sauce", "Wax", "Kief",
    "Hash", "Bubble Hash", "Diamonds", "Live Rosin", "Rosin", "RSO",
    "Live Resin", "Cured Resin", "Resin",
}

# ---------------------------------------------------------------------------
# Infusion type (spec section 14)
# ---------------------------------------------------------------------------
INFUSION_PATTERNS = [
    ("Live Rosin Infused", ["live rosin infused", "live rosin"]),
    ("Live Resin Infused", ["live resin infused", "live resin"]),
    ("Rosin Infused", ["rosin infused", "rosin"]),
    ("Hash Infused", ["hash infused", "hash hole", "hash-hole", "hashhole", "hash"]),
    ("Kief Infused", ["kief infused", "kief", "dusted"]),
    ("Diamond Infused", ["diamond infused", "diamond"]),
    ("Moonrock Infused", ["moonrock", "moon rock"]),
    ("Infused", ["infused"]),
]

NON_INFUSED_MARKERS = ["uninfused", "non-infused", "non infused", "noninfused"]

# ---------------------------------------------------------------------------
# Edible / oral subforms (spec section 6)
# ---------------------------------------------------------------------------
EDIBLE_FORM_PATTERNS = [
    ("Beverage", ["beverage", "drink", "drinks", "seltzer", "soda", "can",
                  "shot", "elixir", "lemonade", "tea", "juice"]),
    ("Gummy", ["gummies", "gummy", "fruit chew", "chews", "chew", "pâte", "pate de fruit"]),
    ("Chocolate", ["chocolate", "chocolates", "truffle", "bar"]),
    ("Capsule", ["capsule", "capsules", "softgel", "soft gel", "caps"]),
    ("Tablet", ["tablet", "tablets"]),
    ("Lozenge", ["lozenge", "lozenges", "troche", "mint", "mints", "hard candy"]),
    ("Baked Good", ["cookie", "cookies", "brownie", "baked", "rice krispie", "krispy"]),
    ("Tincture", ["tincture", "tinctures"]),
]

# ---------------------------------------------------------------------------
# Dominance / strain type normalization (spec section 16)
# ---------------------------------------------------------------------------
DOMINANCE_MAP = {
    "indica": "Indica",
    "sativa": "Sativa",
    "hybrid": "Hybrid",
    "indica-hybrid": "Indica Hybrid",
    "indica hybrid": "Indica Hybrid",
    "sativa-hybrid": "Sativa Hybrid",
    "sativa hybrid": "Sativa Hybrid",
    "sativa dominant": "Sativa Hybrid",
    "indica dominant": "Indica Hybrid",
    "cbd": "CBD",
    "high cbd": "CBD",
    "thc": "THC",
    "balanced": "Balanced",
    "n/a": "Unknown",
    "": "Unknown",
}

# ---------------------------------------------------------------------------
# Descriptor words to strip from product identity (spec section 9)
# ---------------------------------------------------------------------------
DESCRIPTOR_WORDS = {
    "indica", "sativa", "hybrid", "thc", "cbd", "cbg", "cbn", "cbc",
    "live", "resin", "rosin", "cured", "distillate", "solventless",
    "infused", "uninfused", "noninfused", "premium", "indoor", "outdoor",
    "sungrown", "sun", "grown", "single", "source", "small", "batch",
    "limited", "edition", "exotic", "exotics", "top", "shelf", "topshelf",
    "craft", "boutique", "fire", "loud", "high", "potency", "strain",
    "dominant", "balanced", "full", "spectrum", "broad", "pure",
    "diamonds", "diamond", "liquid", "sauce", "badder", "batter", "budder",
    "crumble", "shatter", "kief", "hash", "wax", "rso", "moonrock",
    "flower", "preroll", "pre-roll", "prerolls", "joint", "blunt", "cart",
    "cartridge", "carts", "disposable", "disposables", "aio", "pod", "pods",
    "vape", "vapes", "vaporizer", "gummy", "gummies", "chocolate", "beverage",
    "drink", "capsule", "tablet", "tincture", "edible", "edibles",
    "concentrate", "concentrates", "dab", "dabs", "smalls", "popcorn",
    "shake", "trim", "ground", "whole", "bud", "buds", "nug", "nugs",
    "pack", "packs", "pk", "ct", "count", "single", "singles", "can",
    "free", "battery", "batteries", "bonus", "gift", "promo", "w",
}

# Strain-type / dominance tokens to drop when isolating identity
STRAINTYPE_TOKENS = {
    "indica", "sativa", "hybrid", "thc", "cbd", "balanced",
}
