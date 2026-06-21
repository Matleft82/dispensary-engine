"""Tests anchored on the Normalization Foundation spec examples."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pek_engine.brand import BrandResolver
from pek_engine.models import RawDPL
from pek_engine.normalize import normalize_dpl


def _resolver():
    r = BrandResolver()
    for canonical, aliases in [
        ("MFNY", ["MFNY"]),
        ("Veterans Choice", ["Veteran's Choice", "Vet Choice"]),
        ("Off Hours", ["Off Hours"]),
        ("Nanticoke", ["Nanticoke"]),
        ("Jaunty", ["Jaunty"]),
    ]:
        r._register(canonical, canonical)
        for a in aliases:
            r._register(a, canonical)
    return r


def _raw(title, brand=None, category=None, sub=None, weight=None,
         thc=None, thc_unit=None, cbd=None, cbd_unit=None, strain=None):
    return RawDPL(
        raw_dpl_id="raw_x", batch_id="b", source_dispensary="D",
        source_dispensary_id="d1", source_platform="Dutchie",
        source_product_id="p1", source_product_title=title,
        source_brand=brand, source_category=category, source_subcategory=sub,
        price=10.0, sale_price=None, thc_raw=thc, thc_unit_raw=thc_unit,
        cbd_raw=cbd, cbd_unit_raw=cbd_unit, weight_raw=weight,
        strain_type_raw=strain, image_url=None, product_url=None, raw_payload={})


def test_vape_live_resin_cart():
    n = normalize_dpl(_raw(
        "MFNY - Blueberry 2.0 Live Resin 510 Cartridge 0.5g",
        brand="MFNY", category="Vaporizers", sub="cartridges"), _resolver())
    assert n.normalized_category == "Vapes"
    assert n.normalized_form == "Vape Cartridge"
    assert n.hardware_type == "510 Cartridge"
    assert n.extract_type == "Live Resin"
    assert n.normalized_size == "0.5g"
    assert "blueberry 2.0" in n.normalized_product_name.lower()


def test_flower_size_and_identity():
    n = normalize_dpl(_raw(
        "Veteran's Choice Lilac Diesel 3.5g", brand="Veteran's Choice",
        category="Flower"), _resolver())
    assert n.normalized_brand == "Veterans Choice"  # alias applied
    assert n.normalized_category == "Flower"
    assert n.normalized_size == "3.5g"
    assert "lilac diesel" in n.normalized_product_name.lower()


def test_edible_mg_and_count():
    n = normalize_dpl(_raw(
        "Off Hours Blue Raspberry Gummies 10pk 100mg", brand="Off Hours",
        category="Edibles", sub="gummies", thc="100", thc_unit="MILLIGRAMS"),
        _resolver())
    assert n.normalized_category == "Edibles"
    assert n.normalized_form == "Gummy"
    assert n.count == 10
    assert n.package_thc_mg == 100.0
    assert n.serving_thc_mg == 10.0
    assert "blue raspberry" in n.normalized_product_name.lower()


def test_preroll_count_pack():
    n = normalize_dpl(_raw(
        "Nanticoke Lilac Diesel 5pk Pre-Rolls", brand="Nanticoke",
        category="Pre-Rolls"), _resolver())
    assert n.normalized_category == "Pre-Rolls"
    assert n.count == 5
    assert "lilac diesel" in n.normalized_product_name.lower()


def test_resin_not_rosin():
    resin = normalize_dpl(_raw("MFNY Blue Dream Live Resin 510 Cart 1g",
                               brand="MFNY", category="Vaporizers"), _resolver())
    rosin = normalize_dpl(_raw("MFNY Blue Dream Live Rosin 510 Cart 1g",
                               brand="MFNY", category="Vaporizers"), _resolver())
    assert resin.extract_type == "Live Resin"
    assert rosin.extract_type == "Live Rosin"
    assert resin.proposed_pek != rosin.proposed_pek


def test_cart_not_disposable():
    cart = normalize_dpl(_raw("Jaunty Mango 1g 510 Cartridge Live Resin",
                              brand="Jaunty", category="Vaporizers"), _resolver())
    dispo = normalize_dpl(_raw("Jaunty Mango 1g Disposable Live Resin",
                               brand="Jaunty", category="Vaporizers"), _resolver())
    assert cart.hardware_type == "510 Cartridge"
    assert dispo.hardware_type == "Disposable"
    assert cart.proposed_pek != dispo.proposed_pek


def test_accessory_excluded():
    n = normalize_dpl(_raw("Rolling Tray", category="Accessories"), _resolver())
    assert n.comparison_status == "excluded_accessory"
    assert n.proposed_pek is None


def test_accent_folding_keeps_identity():
    # The 'Rosé' -> 'Ros' truncation bug: accents must fold, not drop letters.
    n = normalize_dpl(_raw("Ayrloom Rosé 10mg THC Beverage", brand="Off Hours",
                           category="Edibles", thc="10", thc_unit="MILLIGRAMS"),
                      _resolver())
    assert "rose" in n.normalized_product_name.lower()
    n2 = normalize_dpl(_raw("Piña Colada Gummies 100mg", brand="Off Hours",
                            category="Edibles", thc="100", thc_unit="MILLIGRAMS"),
                       _resolver())
    assert "pina colada" in n2.normalized_product_name.lower()


def test_ampersand_preserved_as_and():
    n = normalize_dpl(_raw("Off Hours Half & Half 100mg Gummies", brand="Off Hours",
                           category="Edibles", thc="100", thc_unit="MILLIGRAMS"),
                      _resolver())
    assert "half and half" in n.normalized_product_name.lower()


def test_descriptor_does_not_split_identity():
    # The #hash defect: a strain-type descriptor must not change identity.
    a = normalize_dpl(_raw("#Hash Angie Sativa/Hybrid Wax Budder 1g",
                           brand="#HASH", category="Concentrates"), _resolver())
    b = normalize_dpl(_raw("#Hash Angie Wax Budder 1g",
                           brand="#HASH", category="Concentrates"), _resolver())
    assert a.normalized_product_name.lower() == b.normalized_product_name.lower()
    assert a.proposed_pek == b.proposed_pek
