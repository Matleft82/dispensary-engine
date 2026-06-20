"""Data models mirroring the Normalization Foundation v1 tables.

These dataclasses are the in-memory representation of the spec's SQL schemas.
They serialize to JSON and (optionally) to SQLite with the same field names.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


# Comparison status (spec section 4)
ELIGIBLE = "eligible_cannabis"
EXCLUDED_ACCESSORY = "excluded_accessory"
EXCLUDED_MERCH = "excluded_merchandise"
EXCLUDED_NON_CANNABIS = "excluded_non_cannabis"
NEEDS_REVIEW = "needs_review"
BAD_SOURCE_DATA = "bad_source_data"


@dataclass
class RawDPL:
    """Untouched source truth — spec: raw_dispensary_product_listings."""

    raw_dpl_id: str
    batch_id: str
    source_dispensary: str
    source_dispensary_id: str
    source_platform: Optional[str]
    source_product_id: str
    source_product_title: str
    source_brand: Optional[str]
    source_category: Optional[str]
    source_subcategory: Optional[str]
    price: Optional[float]
    sale_price: Optional[float]
    thc_raw: Optional[str]
    thc_unit_raw: Optional[str]
    cbd_raw: Optional[str]
    cbd_unit_raw: Optional[str]
    weight_raw: Optional[str]
    strain_type_raw: Optional[str]
    image_url: Optional[str]
    product_url: Optional[str]
    raw_payload: dict
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    ingest_status: str = "ingested"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NormalizedDPL:
    """Cleaned, field-extracted listing — spec: normalized_dispensary_product_listings."""

    dpl_id: str
    raw_dpl_id: str
    batch_id: str

    source_dispensary: str
    source_dispensary_id: str
    source_platform: Optional[str]
    source_product_id: str
    source_product_title: str
    display_title: str
    search_title: str

    source_brand: Optional[str]
    normalized_brand: Optional[str]
    brand_id: Optional[str]
    brand_confidence: float

    raw_category: Optional[str]
    raw_subcategory: Optional[str]
    normalized_category: Optional[str]
    normalized_form: Optional[str]
    subform: Optional[str]
    hardware_type: Optional[str]

    product_name_raw: Optional[str]
    normalized_product_name: Optional[str]

    size_value: Optional[float]
    size_unit: Optional[str]
    normalized_size: Optional[str]
    unit_weight_grams: Optional[float]
    total_weight_grams: Optional[float]
    count: Optional[int]

    package_thc_mg: Optional[float]
    serving_thc_mg: Optional[float]
    package_cbd_mg: Optional[float]
    serving_cbd_mg: Optional[float]
    cannabinoid_profile: Optional[str]
    ratio: Optional[str]

    extract_type: Optional[str]
    infusion_type: Optional[str]
    dominance_or_type: Optional[str]
    strain_type_reported: Optional[str]

    thc_value: Optional[str]
    cbd_value: Optional[str]

    price: Optional[float]
    sale_price: Optional[float]
    effective_price: Optional[float]

    image_url: Optional[str]
    product_url: Optional[str]

    comparison_status: str
    proposed_pek: Optional[str]
    pek_components: dict = field(default_factory=dict)

    extraction_confidence: float = 0.0
    source_notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MCP:
    """Master Canonical Product — spec: master_canonical_products."""

    mcp_id: str
    pek: str
    canonical_title: str
    search_title: str

    brand_id: Optional[str]
    normalized_brand: str
    normalized_category: str
    normalized_form: Optional[str]
    subform: Optional[str]
    canonical_product_name: str

    normalized_size: Optional[str]
    unit_weight_grams: Optional[float]
    total_weight_grams: Optional[float]
    count: Optional[int]

    package_thc_mg: Optional[float]
    package_cbd_mg: Optional[float]
    cannabinoid_profile: Optional[str]
    ratio: Optional[str]

    extract_type: Optional[str]
    infusion_type: Optional[str]
    hardware_type: Optional[str]
    dominance_or_type: Optional[str]

    canonical_image_url: Optional[str]

    dpl_count: int = 0
    dispensary_count: int = 0
    review_status: str = "provisional"

    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MCPDPLLink:
    """spec: mcp_dpl_links."""

    link_id: str
    mcp_id: str
    dpl_id: str
    match_confidence: float
    match_method: str
    match_reasons: list = field(default_factory=list)
    needs_review: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReviewItem:
    """spec: product_review_queue."""

    review_id: str
    batch_id: str
    issue_type: str
    risk_level: str
    dpl_ids: list
    candidate_mcp_ids: list
    source_titles_compared: list
    reason_for_review: str
    recommended_action: str
    status: str = "open"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DataQualityFlag:
    """spec: data_quality_flags."""

    flag_id: str
    batch_id: str
    dpl_id: str
    source_dispensary: str
    problem_type: str
    problem_description: str
    suggested_fix: Optional[str]
    confidence: float
    status: str = "open"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PriceIndexRow:
    """spec: price_comparison_index."""

    price_index_id: str
    mcp_id: str
    dpl_id: str
    source_dispensary: str
    source_platform: Optional[str]
    canonical_title: str
    normalized_brand: str
    normalized_category: str
    normalized_form: Optional[str]
    normalized_size: Optional[str]
    price: Optional[float]
    sale_price: Optional[float]
    effective_price: Optional[float]
    product_url: Optional[str]
    image_url: Optional[str]
    in_stock: Optional[bool]

    def to_dict(self) -> dict:
        return asdict(self)
