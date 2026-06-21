"""PEK/MCP normalization and price-comparison engine.

Turns raw dispensary product listings (DPLs) into normalized listings,
deterministic Product Equality Keys (PEKs), and Master Canonical Products
(MCPs) so the same real-world product can be compared across dispensaries.

Implements the Normalization Foundation v1 spec: normalize aggressively,
match conservatively, never fabricate missing facts, never mutate source data.
"""

__version__ = "0.1.0"
