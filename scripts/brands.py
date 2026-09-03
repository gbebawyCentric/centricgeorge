"""Per-brand configuration for the daily ecom recap.

The recap emails are three separately themed documents, not one report with a
brand picker, so the workbook is built once per brand. Everything that differs
between them lives here.

Accent colours and the scope line are taken from the rendered emails
(see docs/data-mapping.md); the brand ids and labels match
SANDBOX.SBX_RRAJASEKAR.ECOM_SIGMA_BRAND_CONFIG.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Brand:
    brand_id: str
    label: str            # BRAND_LABEL as it appears in every Snowflake table
    display_name: str     # the banner headline
    accent: str           # banner background, taken from the email
    scope_line: str       # the line under "DAILY ECOM RECAP"
    has_shopify_retail: bool = False
    # Shown instead of the retail tables for brands whose stores are not in
    # Shopify. Joe's is the only one today.
    retail_note: str | None = None
    # Boutiques as (RETAILLOCATIONNAME, column heading), in the order the email
    # lists them across the page.
    stores: tuple[tuple[str, str], ...] = field(default_factory=tuple)


BRANDS: tuple[Brand, ...] = (
    Brand(
        brand_id="hudson-jeans",
        label="Hudson",
        display_name="Hudson Jeans",
        accent="#1B3A4B",
        scope_line="Brand-owned website sales (Nordstrom marketplace excluded)",
    ),
    Brand(
        brand_id="favorite-daughter",
        label="FD",
        display_name="Favorite Daughter",
        accent="#6B1D32",
        scope_line=(
            "Brand-owned website (ecom) — retail boutiques shown separately below."
        ),
        has_shopify_retail=True,
        # RETAILLOCATIONNAME in SHOPIFY_ORDERS_ADF, with the short label the
        # email prints above each column.
        stores=(
            ("Madison Avenue Boutique", "MADISON AVENUE"),
            ("Beverly Hills Boutique", "BEVERLY HILLS"),
            ("Nashville Boutique", "NASHVILLE"),
        ),
    ),
    Brand(
        brand_id="joes-jeans",
        label="Joe's",
        display_name="Joe's Jeans",
        accent="#111111",
        scope_line="Brand-owned website sales",
        retail_note=(
            "Joe's physical retail is on a separate platform (not Shopify). "
            "Retail + DTC total TBD once that feed is connected."
        ),
    ),
)

BY_LABEL = {brand.label: brand for brand in BRANDS}
BY_ID = {brand.brand_id: brand for brand in BRANDS}


def get(name: str) -> Brand:
    """Look a brand up by label ("FD") or id ("favorite-daughter")."""
    if name in BY_LABEL:
        return BY_LABEL[name]
    if name in BY_ID:
        return BY_ID[name]
    known = ", ".join(b.label for b in BRANDS)
    raise KeyError(f"unknown brand {name!r} — expected one of: {known}")
