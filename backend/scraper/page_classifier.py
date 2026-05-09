"""
backend/scraper/page_classifier.py
─────────────────────────────────────────────────────────────────
Fast rule-based page type classification.
No LLM. Runs in under 10ms per page using URL patterns, DOM
landmarks, Schema.org metadata, and OG tags.

Priority order:
  1. Schema.org @type (most reliable when present)
  2. URL pattern matching
  3. DOM landmark detection
  4. OG tags
  5. H1/H2 text keywords
  6. Default → OTHER
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from backend.scraper.models import PageType


# ── URL pattern rules ─────────────────────────────────────────

_URL_PATTERNS: list[tuple[re.Pattern, PageType]] = [
    (re.compile(r'/(cart|basket|trolley|bag)(\?|/|$)', re.I), PageType.CART),
    (re.compile(r'/(checkout|check-out|check_out)(\?|/|$)', re.I), PageType.CHECKOUT),
    (re.compile(r'/(payment|pay|billing)(\?|/|$)', re.I), PageType.PAYMENT),
    (re.compile(r'/(order[-_]?(confirmation|complete|success|review|summary))(\?|/|$)', re.I), PageType.ORDER_CONFIRM),
    (re.compile(r'/(login|sign[-_]?in|signin|auth)(\?|/|$)', re.I), PageType.LOGIN_GATE),
    (re.compile(r'/(search|results|find|query)(\?|/|$)', re.I), PageType.SEARCH_RESULTS),
    # Product page patterns
    (re.compile(r'/product[s]?/[^/]+', re.I), PageType.PRODUCT),
    (re.compile(r'/item[s]?/[^/]+', re.I), PageType.PRODUCT),
    (re.compile(r'/dp/[A-Z0-9]{10}', re.I), PageType.PRODUCT),          # Amazon ASIN
    (re.compile(r'/p/\d+', re.I), PageType.PRODUCT),                     # numeric product ID
    (re.compile(r'/[^/]+-\d{6,}(\.html)?$', re.I), PageType.PRODUCT),  # slug with numeric ID
    (re.compile(r'/(category|cat|collection|department|c)/[^/]+', re.I), PageType.CATEGORY),
]

# ── Schema.org type rules ─────────────────────────────────────

_SCHEMA_TYPE_MAP: dict[str, PageType] = {
    'product':         PageType.PRODUCT,
    'productgroup':    PageType.PRODUCT,
    'offer':           PageType.PRODUCT,
    'shoppingcart':    PageType.CART,
    'order':           PageType.ORDER_CONFIRM,
    'checkout':        PageType.CHECKOUT,
}

# ── H1/H2 keyword rules ───────────────────────────────────────

_HEADING_KEYWORDS: list[tuple[list[str], PageType]] = [
    (['your cart', 'your basket', 'shopping cart', 'shopping bag'], PageType.CART),
    (['checkout', 'check out', 'place your order'], PageType.CHECKOUT),
    (['payment', 'payment details', 'billing'], PageType.PAYMENT),
    (['order confirmed', 'order placed', 'thank you for your order', 'order complete'], PageType.ORDER_CONFIRM),
    (['sign in', 'log in', 'login', 'create account'], PageType.LOGIN_GATE),
    (['search results', 'results for', 'showing results'], PageType.SEARCH_RESULTS),
]


def classify_page(
    url: str,
    schema_types: list[str],
    og_type: str | None,
    headings: list[str],
    has_add_to_cart: bool,
    has_quantity_selector: bool,
    has_payment_form: bool,
    has_subtotal: bool,
) -> PageType:
    """
    Classify a page into a PageType using the priority cascade.

    Args:
        url:                 The final URL (after redirects)
        schema_types:        List of @type values from ld+json scripts
        og_type:             og:type meta content
        headings:            List of h1/h2 innerText values
        has_add_to_cart:     True if "add to cart" button detected
        has_quantity_selector: True if a quantity number input is present
        has_payment_form:    True if credit-card form fields present
        has_subtotal:        True if subtotal/total elements present

    Returns:
        PageType enum value
    """

    # ── 1. Schema.org ─────────────────────────────────────────
    for schema_type in schema_types:
        normalised = schema_type.lower().strip()
        for key, page_type in _SCHEMA_TYPE_MAP.items():
            if key in normalised:
                return page_type

    # ── 2. URL pattern ────────────────────────────────────────
    path = urlparse(url).path
    for pattern, page_type in _URL_PATTERNS:
        if pattern.search(path):
            return page_type

    # ── 3. DOM landmarks ──────────────────────────────────────
    if has_payment_form:
        return PageType.PAYMENT
    if has_quantity_selector and has_subtotal:
        return PageType.CART
    if has_quantity_selector and has_add_to_cart:
        return PageType.PRODUCT

    # ── 4. OG type ────────────────────────────────────────────
    if og_type:
        og_lower = og_type.lower()
        if 'product' in og_lower:
            return PageType.PRODUCT

    # ── 5. Heading keywords ───────────────────────────────────
    heading_text = ' '.join(h.lower() for h in headings)
    for keywords, page_type in _HEADING_KEYWORDS:
        if any(kw in heading_text for kw in keywords):
            return page_type

    # ── 6. Fallback ───────────────────────────────────────────
    path_parts = [p for p in path.split('/') if p]
    if not path_parts:
        return PageType.HOME

    return PageType.OTHER