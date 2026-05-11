"""
backend/scraper/models.py
─────────────────────────────────────────────────────────────────
All Pydantic data models for the scraper layer.
These are the canonical schemas that travel from the scraper
through Redis to every agent.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Page Type ─────────────────────────────────────────────────

class PageType(str, Enum):
    PRODUCT        = "PRODUCT"
    CART           = "CART"
    CHECKOUT       = "CHECKOUT"
    PAYMENT        = "PAYMENT"
    SEARCH_RESULTS = "SEARCH_RESULTS"
    CATEGORY       = "CATEGORY"
    HOME           = "HOME"
    LOGIN_GATE     = "LOGIN_GATE"
    ORDER_CONFIRM  = "ORDER_CONFIRM"
    OTHER          = "OTHER"


# ── Element-level models ──────────────────────────────────────

class ButtonElement(BaseModel):
    text: str
    aria_label: str | None = None
    href: str | None = None
    actual_href: str | None = None          # resolved after JS processing
    domain_mismatch: bool = False
    redirect_chain: list[str] = []
    is_in_modal: bool = False
    is_in_sticky: bool = False
    bg_color: str | None = None             # computed CSS background-color
    text_color: str | None = None           # computed CSS color
    font_size: str | None = None
    css_selector: str | None = None
    bounding_box: dict[str, float] | None = None  # x, y, width, height
    is_close_button: bool = False
    data_attributes: dict[str, str] = {}


class FormField(BaseModel):
    tag: str                                # input | select | textarea
    input_type: str | None = None           # text | checkbox | radio | hidden…
    name: str | None = None
    label_text: str | None = None
    placeholder: str | None = None
    value: str | None = None               # pre-filled value
    is_checked: bool = False               # for checkboxes
    is_pre_checked: bool = False           # checked without user interaction
    is_required: bool = False
    is_hidden: bool = False
    css_selector: str | None = None


class FormElement(BaseModel):
    form_id: str | None = None
    action: str | None = None
    method: str = "GET"
    fields: list[FormField] = []
    has_hidden_consent: bool = False        # has hidden pre-consented fields
    pre_checked_count: int = 0


class PriceElement(BaseModel):
    text: str                               # raw displayed text e.g. "$29.99"
    amount: float | None = None            # parsed numeric value
    currency: str | None = None
    original_price: float | None = None   # "was" price if present
    context_before: str | None = None     # sibling text before
    context_after: str | None = None      # sibling text after
    location: str | None = None           # "product_section" | "cart_summary" | "checkout_total"
    css_selector: str | None = None
    bounding_box: dict[str, float] | None = None
    schema_sourced: bool = False           # came from ld+json structured data


class SupplementalCharge(BaseModel):
    label: str
    amount: float | None = None
    currency: str | None = None
    is_pre_selected: bool = False          # automatically added, user must opt-out
    is_optional: bool = True
    css_selector: str | None = None


class OverlayElement(BaseModel):
    overlay_type: str                       # "modal" | "banner" | "toast" | "sticky"
    text: str
    html: str | None = None
    trigger_delay_ms: int = 0              # ms after page load it appeared
    appeared_autonomously: bool = False    # True if appeared without user action
    viewport_coverage_pct: float = 0.0    # % of viewport covered
    has_close_button: bool = False
    close_button_prominent: bool = True
    blocks_interaction: bool = False       # pointer-events blocks background
    css_selector: str | None = None
    bounding_box: dict[str, float] | None = None
    contains_form: bool = False
    contains_cta: bool = False


class TimerElement(BaseModel):
    text: str                               # displayed text e.g. "00:09:47"
    is_counting_down: bool = False
    css_selector: str | None = None
    context: str | None = None  
    
# Add this class — place it alongside the other element models
# (after HiddenElement, before ScrapedPage)

class TextElement(BaseModel):
    """
    A single visible text node captured from the page.
    Preserves tag, location, and surrounding context so agents
    can detect dark patterns purely from text content.
    """
    tag: str                              # h1, p, span, div, button …
    text: str                             # the actual text content
    location: str                         # header | footer | modal | banner |
                                          # cart | checkout | product | body …
    is_visible: bool = True
    is_in_fixed: bool = False             # True → inside fixed/sticky element
    z_index: int = 0
    bbox: dict | None = None             # {x, y, width, height}
    parent_tag: str | None = None
    parent_class: str | None = None
    prev_text: str | None = None         # sibling context
    next_text: str | None = None              # surrounding text for context


class HiddenElement(BaseModel):
    tag: str
    text: str | None = None
    reason: str                            # "display:none" | "visibility:hidden" | "opacity:0" | "offscreen"
    is_form_field: bool = False
    name: str | None = None
    value: str | None = None
    css_selector: str | None = None


class LinkElement(BaseModel):
    text: str
    displayed_url: str | None = None
    actual_href: str | None = None
    is_external: bool = False
    domain_mismatch: bool = False         # visible text domain ≠ href domain
    is_sponsored: bool = False
    css_selector: str | None = None
    bounding_box: dict[str, float] | None = None


class NetworkRequest(BaseModel):
    url: str
    method: str
    resource_type: str                    # "xhr" | "fetch" | "script" | "image" …
    is_auto_triggered: bool = True        # no user action triggered it
    is_tracking: bool = False
    is_cart_mutation: bool = False        # posts to cart/basket endpoints
    timestamp_ms: float = 0.0


class DomMutation(BaseModel):
    type: str                             # "childList" | "attributes" | "characterData"
    target_selector: str | None = None
    added_nodes_count: int = 0
    removed_nodes_count: int = 0
    attribute_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    timestamp_ms: float = 0.0            # ms since page load


class SchemaOrgData(BaseModel):
    type: str | None = None              # "Product" | "ShoppingCart" | "Order" …
    name: str | None = None
    price: float | None = None
    currency: str | None = None
    original_price: float | None = None
    availability: str | None = None
    raw: dict[str, Any] = {}


# ── Top-level scraped page payload ────────────────────────────

class ScrapedPage(BaseModel):
    # Identity
    scrape_id: str = Field(default_factory=_new_id)
    session_id: str
    url: str
    final_url: str                        # after redirects
    title: str
    page_type: PageType

    # Content
    full_html: str
    full_text: str                        # innerText stripped of markup
    lang: str | None = None

    # Structured extractions
    buttons: list[ButtonElement] = []
    links: list[LinkElement] = []
    forms: list[FormElement] = []
    prices: list[PriceElement] = []
    supplemental_charges: list[SupplementalCharge] = []
    overlays: list[OverlayElement] = []
    timers: list[TimerElement] = []
    hidden_elements: list[HiddenElement] = []
    schema_org: list[SchemaOrgData] = []
    text_elements: list[TextElement] = []  

    # Behavioral signals
    network_requests: list[NetworkRequest] = []
    dom_mutations: list[DomMutation] = []
    auto_popup_count: int = 0
    auto_cart_mutations: list[NetworkRequest] = []

    # Price reconciliation (cart/checkout pages)
    cart_line_items: list[dict[str, Any]] = []
    displayed_total: float | None = None
    computed_subtotal: float | None = None
    price_gap: float | None = None       # displayed_total - computed_subtotal

    # Screenshot
    screenshot_b64: str | None = None    # base64 JPEG — stored separately in Redis
    screenshot_key: str | None = None    # Redis key pointing to screenshot

    # Metadata
    scrape_duration_ms: int = 0
    scraped_at: datetime = Field(default_factory=_utcnow)
    page_height: int = 0
    viewport_width: int = 1920
    viewport_height: int = 1080


# ── Session models ─────────────────────────────────────────────

class ScrapeSession(BaseModel):
    session_id: str
    tab_id: str | None = None
    scrape_ids: list[str] = []
    page_types: list[PageType] = []
    urls: list[str] = []
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ── Agent routing payload models ──────────────────────────────

class NLPAgentPayload(BaseModel):
    """Sent directly to NLP Agent — current page only."""
    scrape_id: str
    session_id: str
    url: str
    page_type: PageType
    full_text: str
    buttons: list[ButtonElement]
    overlays: list[OverlayElement]
    forms: list[FormElement]
    timers: list[TimerElement]
    links: list[LinkElement]
    text_elements: list[TextElement] = []


class VisualAgentPayload(BaseModel):
    """Sent directly to Visual Agent — current snapshot."""
    scrape_id: str
    session_id: str
    url: str
    page_type: PageType
    screenshot_key: str                  # Redis key — agent fetches JPEG itself
    overlay_elements: list[OverlayElement]
    price_bounding_boxes: list[dict[str, Any]]
    link_elements: list[LinkElement]
    sponsored_candidates: list[LinkElement]


class PricingAgentPayload(BaseModel):
    """Sent to Pricing Agent — current + previous product page."""
    session_id: str
    current_scrape_id: str
    current_page_type: PageType
    current_url: str
    current_prices: list[PriceElement]
    current_cart_items: list[dict[str, Any]]
    supplemental_charges: list[SupplementalCharge]
    displayed_total: float | None
    computed_subtotal: float | None
    price_gap: float | None
    # Previous product page (may be None if no prior scrape)
    previous_scrape_id: str | None = None
    previous_url: str | None = None
    previous_prices: list[PriceElement] = []
    # Pre-computed cross-page diff
    price_diffs: list[dict[str, Any]] = []


class BehavioralAgentPayload(BaseModel):
    """Sent to Behavioral Agent — current + previous page behavioral data."""
    session_id: str
    current_scrape_id: str
    current_url: str
    current_page_type: PageType
    current_mutations: list[DomMutation]
    current_network_requests: list[NetworkRequest]
    current_auto_cart_mutations: list[NetworkRequest]
    current_overlays: list[OverlayElement]
    redirect_traps: list[LinkElement]
    auto_popup_count: int
    # Previous page (may be None on first scrape in session)
    previous_scrape_id: str | None = None
    previous_url: str | None = None
    previous_mutations: list[DomMutation] = []
    previous_network_requests: list[NetworkRequest] = []
    popup_timeline: list[dict[str, Any]] = []    # cross-page overlay timeline