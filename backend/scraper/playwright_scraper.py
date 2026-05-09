"""
backend/scraper/playwright_scraper.py
─────────────────────────────────────────────────────────────────
Main scraper orchestrator.

One public entry point:
    result: ScrapedPage = await scrape(url, session_id)

Internally:
  1. Check out a browser context from the pool
  2. Open a new page with network interception
  3. Navigate with the layered wait cascade
  4. Run the 2-second behavioral observation window
  5. Execute all extractors in parallel
  6. Classify page type
  7. Build and return ScrapedPage

All network requests are intercepted to detect auto-triggered
cart mutations and tracking pixels.
"""
from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

import structlog
from playwright.async_api import Page, Request, Response, Route

from backend.scraper.browser_pool import get_browser_pool
from backend.scraper.extractors import (
    COLLECT_MUTATIONS_JS,
    EXTRACT_BUTTONS_JS,
    EXTRACT_CART_ITEMS_JS,
    EXTRACT_FORMS_JS,
    EXTRACT_HIDDEN_ELEMENTS_JS,
    EXTRACT_LINKS_JS,
    EXTRACT_METADATA_JS,
    EXTRACT_OVERLAYS_JS,
    EXTRACT_PRICES_JS,
    EXTRACT_SCHEMA_ORG_JS,
    EXTRACT_SUPPLEMENTAL_CHARGES_JS,
    EXTRACT_TIMERS_JS,
    INJECT_MUTATION_OBSERVER_JS,
)
from backend.scraper.models import (
    BehavioralAgentPayload,
    ButtonElement,
    DomMutation,
    FormElement,
    HiddenElement,
    LinkElement,
    NetworkRequest,
    NLPAgentPayload,
    OverlayElement,
    PageType,
    PriceElement,
    PricingAgentPayload,
    ScrapedPage,
    SchemaOrgData,
    SupplementalCharge,
    TimerElement,
    VisualAgentPayload,
)
from backend.scraper.page_classifier import classify_page
from config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── Cart endpoint patterns — detect auto-cart mutations ───────
_CART_PATTERNS = [
    '/cart', '/basket', '/bag', '/add-to-cart',
    'addtocart', 'add_to_cart', '/checkout/cart',
    'lineItems', 'line_items',
]

_TRACKING_PATTERNS = [
    'analytics', 'tracking', 'pixel', 'beacon',
    'facebook.com/tr', 'doubleclick', 'googletagmanager',
    'hotjar', 'clarity.ms', 'mixpanel',
]


# ═══════════════════════════════════════════════════════════════
#  MAIN SCRAPE FUNCTION
# ═══════════════════════════════════════════════════════════════

async def scrape(url: str, session_id: str) -> ScrapedPage:
    """
    Scrape a URL and return a fully populated ScrapedPage.

    This is the only public function in this module.
    All complexity is encapsulated here.
    """
    start_ts = time.perf_counter()
    log = logger.bind(url=url, session_id=session_id)
    log.info("scrape_started")

    pool = get_browser_pool()

    async with pool.acquire() as ctx:
        page = await ctx.new_page()
        try:
            result = await _execute_scrape(page, url, session_id, log)
        finally:
            await page.close()

    result.scrape_duration_ms = int((time.perf_counter() - start_ts) * 1000)
    log.info(
        "scrape_complete",
        page_type=result.page_type,
        duration_ms=result.scrape_duration_ms,
        buttons=len(result.buttons),
        overlays=len(result.overlays),
        prices=len(result.prices),
    )
    return result


async def _execute_scrape(
    page: Page,
    url: str,
    session_id: str,
    log: Any,
) -> ScrapedPage:
    """Run the full scrape pipeline on an open Page object."""

    # ── Network interception ──────────────────────────────────
    network_requests: list[NetworkRequest] = []
    page_load_start = time.perf_counter()

    async def _on_request(request: Request) -> None:
        try:
            req_url = request.url
            resource_type = request.resource_type

            is_cart = any(p in req_url.lower() for p in _CART_PATTERNS)
            is_tracking = any(p in req_url.lower() for p in _TRACKING_PATTERNS)
            elapsed_ms = (time.perf_counter() - page_load_start) * 1000

            network_requests.append(NetworkRequest(
                url=req_url,
                method=request.method,
                resource_type=resource_type,
                is_auto_triggered=True,          # all requests during load are auto
                is_tracking=is_tracking,
                is_cart_mutation=is_cart and request.method in ("POST", "PUT", "PATCH"),
                timestamp_ms=elapsed_ms,
            ))
        except Exception:
            pass

    page.on("request", _on_request)

    # Block heavy resources that slow scraping without adding value
    await page.route(
        "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot}",
        lambda route: _block_or_continue(route),
    )

    # ── Step 1: Navigate ──────────────────────────────────────
    log.debug("navigation_starting")
    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=settings.playwright_timeout,
        )
    except Exception as exc:
        log.warning("navigation_error", error=str(exc))
        # Try again with a more lenient wait condition
        await page.goto(url, wait_until="commit", timeout=settings.playwright_timeout)

    final_url = page.url

    # ── Step 2: Network quiet wait ────────────────────────────
    log.debug("waiting_network_idle")
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass  # Timeout is fine — move on

    # ── Step 3: JS mutation stability ────────────────────────
    log.debug("waiting_dom_stability")
    await _wait_for_dom_stability(page, quiet_period_ms=500, timeout_ms=8000)

    # ── Step 4: Handle consent walls ─────────────────────────
    await _dismiss_consent_walls(page)

    # ── Step 5: Scroll trigger (lazy-load) ───────────────────
    log.debug("triggering_scroll")
    await _scroll_page(page)

    # ── Step 6: Inject mutation observer BEFORE observation window
    await page.evaluate(INJECT_MUTATION_OBSERVER_JS)
    overlay_count_before = await _count_overlays(page)
    observation_start = time.perf_counter()

    # ── Step 7: Behavioral observation window (2 seconds) ────
    log.debug("observation_window_open")
    # Simulate mouse movement to trigger hover-based dark patterns
    await page.mouse.move(960, 540)
    await asyncio.sleep(2.0)   # The observation window — dark patterns fire here
    observation_elapsed_ms = int((time.perf_counter() - observation_start) * 1000)

    # ── Step 8: Collect mutation log ─────────────────────────
    raw_mutations: list[dict] = await page.evaluate(COLLECT_MUTATIONS_JS) or []
    dom_mutations = [
        DomMutation(**m) for m in raw_mutations
        if isinstance(m, dict)
    ]

    # Count auto-appearing overlays
    overlay_count_after = await _count_overlays(page)
    auto_popup_count = max(0, overlay_count_after - overlay_count_before)

    # ── Step 9: Screenshot ───────────────────────────────────
    log.debug("taking_screenshot")
    screenshot_bytes = await page.screenshot(
        full_page=True,
        type="jpeg",
        quality=70,
    )
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

    # ── Step 10: Parallel extraction ─────────────────────────
    log.debug("parallel_extraction_starting")
    (
        raw_buttons,
        raw_forms,
        raw_prices,
        raw_supplemental,
        raw_overlays,
        raw_timers,
        raw_hidden,
        raw_links,
        raw_schema,
        raw_cart_items,
        raw_metadata,
        full_html,
        full_text,
    ) = await asyncio.gather(
        page.evaluate(EXTRACT_BUTTONS_JS),
        page.evaluate(EXTRACT_FORMS_JS),
        page.evaluate(EXTRACT_PRICES_JS),
        page.evaluate(EXTRACT_SUPPLEMENTAL_CHARGES_JS),
        page.evaluate(EXTRACT_OVERLAYS_JS),
        page.evaluate(EXTRACT_TIMERS_JS),
        page.evaluate(EXTRACT_HIDDEN_ELEMENTS_JS),
        page.evaluate(EXTRACT_LINKS_JS),
        page.evaluate(EXTRACT_SCHEMA_ORG_JS),
        page.evaluate(EXTRACT_CART_ITEMS_JS),
        page.evaluate(EXTRACT_METADATA_JS),
        page.content(),
        page.evaluate("document.body.innerText"),
        return_exceptions=False,
    )

    # ── Step 11: Parse raw extraction results ─────────────────
    buttons     = _parse_list(raw_buttons, ButtonElement)
    forms       = _parse_list(raw_forms, FormElement)
    prices      = _parse_list(raw_prices, PriceElement)
    supplemental= _parse_list(raw_supplemental, SupplementalCharge)
    overlays    = _parse_list(raw_overlays, OverlayElement)
    timers      = _parse_list(raw_timers, TimerElement)
    hidden_els  = _parse_list(raw_hidden, HiddenElement)
    links       = _parse_list(raw_links, LinkElement)
    schema_items= _parse_list(raw_schema, SchemaOrgData)
    metadata    = raw_metadata if isinstance(raw_metadata, dict) else {}
    cart_items  = raw_cart_items if isinstance(raw_cart_items, list) else []

    # Annotate overlays that appeared after the observation window start
    for overlay in overlays:
        # If a mutation added a high-z-index element, it appeared autonomously
        for mutation in dom_mutations:
            if (
                mutation.added_nodes_count > 0
                and mutation.timestamp_ms < observation_elapsed_ms
                and overlay.css_selector
                and mutation.target_selector
                and any(
                    cls in (overlay.css_selector or "")
                    for cls in (mutation.target_selector.split(".")[1:] or [""])
                )
            ):
                overlay.appeared_autonomously = True
                overlay.trigger_delay_ms = int(mutation.timestamp_ms)
                break

    # ── Step 12: Page classification ─────────────────────────
    schema_types = [s.type for s in schema_items if s.type]
    headings: list[str] = await page.evaluate("""
        Array.from(document.querySelectorAll('h1,h2'))
            .map(h => h.innerText.trim())
            .filter(t => t.length > 0)
            .slice(0, 10)
    """) or []

    has_add_to_cart = any(
        'add to cart' in (b.text or '').lower() or
        'add to bag' in (b.text or '').lower()
        for b in buttons
    )
    has_quantity_selector: bool = await page.evaluate(
        "document.querySelector('input[type=\"number\"][min]') !== null"
    )
    has_payment_form: bool = await page.evaluate(
        "document.querySelector('input[name*=\"card\"], input[autocomplete*=\"cc-\"]') !== null"
    )
    has_subtotal: bool = bool([
        p for p in prices
        if p.location and 'cart' in p.location.lower()
    ])

    page_type = classify_page(
        url=final_url,
        schema_types=schema_types,
        og_type=metadata.get("og_type"),
        headings=headings,
        has_add_to_cart=has_add_to_cart,
        has_quantity_selector=has_quantity_selector,
        has_payment_form=has_payment_form,
        has_subtotal=has_subtotal,
    )

    # ── Step 13: Price reconciliation (cart/checkout) ─────────
    displayed_total: float | None = None
    computed_subtotal: float | None = None
    price_gap: float | None = None

    if page_type in (PageType.CART, PageType.CHECKOUT, PageType.PAYMENT):
        cart_prices = [p.amount for p in prices if p.amount and p.location != 'schema_org']
        if cart_prices:
            computed_subtotal = sum(cart_prices)

        # Try to find the displayed total element
        total_price = next(
            (p for p in prices if p.location in ('checkout_total', 'order_summary')),
            None
        )
        if total_price and total_price.amount:
            displayed_total = total_price.amount
            if computed_subtotal:
                price_gap = round(displayed_total - computed_subtotal, 2)

    # ── Step 14: Auto-cart mutations from network log ─────────
    auto_cart = [r for r in network_requests if r.is_cart_mutation]

    # ── Step 15: Redirect trap detection ─────────────────────
    redirect_traps = [l for l in links if l.domain_mismatch or l.is_sponsored]
    sponsored_candidates = [l for l in links if l.is_sponsored]

    # ── Step 16: Screenshot Redis key (set by session store) ──
    screenshot_key = f"scrape:{session_id}:screenshot:{_extract_scrape_id()}"

    # ── Step 17: Assemble ScrapedPage ─────────────────────────
    return ScrapedPage(
        session_id=session_id,
        url=url,
        final_url=final_url,
        title=metadata.get("title", ""),
        page_type=page_type,
        full_html=full_html or "",
        full_text=(full_text or "")[:50_000],   # cap at 50KB
        lang=metadata.get("lang"),
        buttons=buttons,
        links=links,
        forms=forms,
        prices=prices,
        supplemental_charges=supplemental,
        overlays=overlays,
        timers=timers,
        hidden_elements=hidden_els,
        schema_org=schema_items,
        network_requests=network_requests[:200],   # cap to 200 requests
        dom_mutations=dom_mutations[:500],
        auto_popup_count=auto_popup_count,
        auto_cart_mutations=auto_cart,
        cart_line_items=cart_items,
        displayed_total=displayed_total,
        computed_subtotal=computed_subtotal,
        price_gap=price_gap,
        screenshot_b64=screenshot_b64,
        screenshot_key=screenshot_key,
        page_height=metadata.get("page_height", 0),
        viewport_width=metadata.get("viewport_width", 1920),
        viewport_height=metadata.get("viewport_height", 1080),
    )


# ═══════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

async def _wait_for_dom_stability(
    page: Page,
    quiet_period_ms: int = 500,
    timeout_ms: int = 8000,
) -> None:
    """
    Wait until the DOM has been quiet (no mutations) for `quiet_period_ms`.
    Gives up after `timeout_ms` total elapsed.
    Uses Playwright's evaluate to inject a MutationObserver that resolves
    once a quiet period is reached.
    """
    try:
        await page.evaluate(f"""
            () => new Promise((resolve) => {{
                let timer = null;
                const obs = new MutationObserver(() => {{
                    clearTimeout(timer);
                    timer = setTimeout(() => {{ obs.disconnect(); resolve(); }}, {quiet_period_ms});
                }});
                obs.observe(document.body, {{ childList: true, subtree: true, attributes: true }});
                // Fallback resolve after timeout
                timer = setTimeout(() => {{ obs.disconnect(); resolve(); }}, {quiet_period_ms});
                // Hard timeout
                setTimeout(() => {{ obs.disconnect(); resolve(); }}, {timeout_ms});
            }})
        """)
    except Exception:
        pass


async def _dismiss_consent_walls(page: Page) -> None:
    """
    Auto-click accept/dismiss on the most common cookie consent frameworks.
    Records that a consent wall was present for behavioral data.
    """
    consent_button_selectors = [
        # OneTrust
        '#onetrust-accept-btn-handler',
        '.onetrust-accept-btn-handler',
        # Cookiebot
        '#CybotCookiebotDialogBodyButtonAccept',
        # TrustArc
        '.truste_popframe button.call',
        # Generic accept patterns
        'button[id*="accept"]',
        'button[class*="accept"]',
        'button[id*="agree"]',
        'button[class*="agree"]',
        # Text-based matching done via evaluate
    ]

    for selector in consent_button_selectors:
        try:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                await btn.click(timeout=2000)
                await asyncio.sleep(0.3)
                return
        except Exception:
            pass

    # Fallback: text-content matching for "Accept", "Accept All", "I Agree"
    try:
        await page.evaluate("""
            const keywords = ['accept all', 'accept cookies', 'i agree', 'agree & close',
                              'allow all', 'allow cookies', 'got it'];
            const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
            for (const btn of buttons) {
                const text = (btn.innerText || '').trim().toLowerCase();
                if (keywords.some(k => text.includes(k))) {
                    btn.click();
                    break;
                }
            }
        """)
        await asyncio.sleep(0.3)
    except Exception:
        pass


async def _scroll_page(page: Page) -> None:
    """
    Programmatic scroll to trigger lazy-loading at 25%, 50%, 75%, 100%.
    """
    try:
        scroll_height: int = await page.evaluate(
            "document.body.scrollHeight || document.documentElement.scrollHeight"
        )
        for fraction in (0.25, 0.50, 0.75, 1.0):
            target = int(scroll_height * fraction)
            await page.evaluate(f"window.scrollTo(0, {target})")
            await asyncio.sleep(0.2)
        # Scroll back to top so screenshot captures the top of the page
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.2)
    except Exception:
        pass


async def _count_overlays(page: Page) -> int:
    """Count currently visible fixed/sticky high-z elements."""
    try:
        count: int = await page.evaluate("""
            Array.from(document.querySelectorAll('*')).filter(el => {
                const s = window.getComputedStyle(el);
                return (s.position === 'fixed' || s.position === 'sticky') &&
                       parseInt(s.zIndex || '0') > 50 &&
                       s.display !== 'none' &&
                       s.visibility !== 'hidden';
            }).length
        """)
        return count
    except Exception:
        return 0


async def _block_or_continue(route: Route) -> None:
    """Block images/fonts to speed up scraping."""
    try:
        await route.abort()
    except Exception:
        try:
            await route.continue_()
        except Exception:
            pass


def _parse_list(raw: Any, model_class: type) -> list:
    """
    Safely parse a list of dicts from page.evaluate() into Pydantic models.
    Invalid items are silently skipped.
    """
    if not isinstance(raw, list):
        return []
    results = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            results.append(model_class(**item))
        except Exception:
            pass
    return results


def _extract_scrape_id() -> str:
    """Generate a scrape-specific ID suffix."""
    import uuid
    return str(uuid.uuid4())[:8]


# ═══════════════════════════════════════════════════════════════
#  AGENT PAYLOAD BUILDERS
# ═══════════════════════════════════════════════════════════════

def build_nlp_payload(page: ScrapedPage) -> NLPAgentPayload:
    """Build the payload sent directly to the NLP Agent."""
    return NLPAgentPayload(
        scrape_id=page.scrape_id,
        session_id=page.session_id,
        url=page.url,
        page_type=page.page_type,
        full_text=page.full_text,
        buttons=page.buttons,
        overlays=page.overlays,
        forms=page.forms,
        timers=page.timers,
        links=page.links,
    )


def build_visual_payload(page: ScrapedPage) -> VisualAgentPayload:
    """Build the payload sent directly to the Visual Agent."""
    price_bboxes = [
        {"selector": p.css_selector, "bbox": p.bounding_box, "text": p.text}
        for p in page.prices
        if p.bounding_box
    ]
    sponsored = [l for l in page.links if l.is_sponsored]
    return VisualAgentPayload(
        scrape_id=page.scrape_id,
        session_id=page.session_id,
        url=page.url,
        page_type=page.page_type,
        screenshot_key=page.screenshot_key or "",
        overlay_elements=page.overlays,
        price_bounding_boxes=price_bboxes,
        link_elements=page.links,
        sponsored_candidates=sponsored,
    )


def build_pricing_payload(
    current: ScrapedPage,
    previous: ScrapedPage | None,
) -> PricingAgentPayload:
    """Build the comparison bundle sent to the Pricing Agent."""
    price_diffs: list[dict] = []
    if previous:
        prev_prices = {p.text: p.amount for p in previous.prices if p.amount}
        for p in current.prices:
            if p.amount and p.text in prev_prices:
                prev_amount = prev_prices[p.text]
                if prev_amount and abs(p.amount - prev_amount) > 0.001:
                    price_diffs.append({
                        "item": p.text,
                        "price_on_previous_page": prev_amount,
                        "price_on_current_page": p.amount,
                        "variance": round(p.amount - prev_amount, 2),
                        "variance_pct": round(
                            ((p.amount - prev_amount) / prev_amount) * 100, 2
                        ) if prev_amount else None,
                    })

    return PricingAgentPayload(
        session_id=current.session_id,
        current_scrape_id=current.scrape_id,
        current_page_type=current.page_type,
        current_url=current.url,
        current_prices=current.prices,
        current_cart_items=current.cart_line_items,
        supplemental_charges=current.supplemental_charges,
        displayed_total=current.displayed_total,
        computed_subtotal=current.computed_subtotal,
        price_gap=current.price_gap,
        previous_scrape_id=previous.scrape_id if previous else None,
        previous_url=previous.url if previous else None,
        previous_prices=previous.prices if previous else [],
        price_diffs=price_diffs,
    )


def build_behavioral_payload(
    current: ScrapedPage,
    previous: ScrapedPage | None,
) -> BehavioralAgentPayload:
    """Build the comparison bundle sent to the Behavioral Agent."""
    redirect_traps = [l for l in current.links if l.domain_mismatch]
    popup_timeline: list[dict] = []

    # Build popup timeline from both pages' overlays
    if previous:
        for ov in previous.overlays:
            popup_timeline.append({
                "scrape_id": previous.scrape_id,
                "url": previous.url,
                "type": ov.overlay_type,
                "delay_ms": ov.trigger_delay_ms,
                "autonomous": ov.appeared_autonomously,
            })
    for ov in current.overlays:
        popup_timeline.append({
            "scrape_id": current.scrape_id,
            "url": current.url,
            "type": ov.overlay_type,
            "delay_ms": ov.trigger_delay_ms,
            "autonomous": ov.appeared_autonomously,
        })

    return BehavioralAgentPayload(
        session_id=current.session_id,
        current_scrape_id=current.scrape_id,
        current_url=current.url,
        current_page_type=current.page_type,
        current_mutations=current.dom_mutations,
        current_network_requests=current.network_requests,
        current_auto_cart_mutations=current.auto_cart_mutations,
        current_overlays=current.overlays,
        redirect_traps=redirect_traps,
        auto_popup_count=current.auto_popup_count,
        previous_scrape_id=previous.scrape_id if previous else None,
        previous_url=previous.url if previous else None,
        previous_mutations=previous.dom_mutations if previous else [],
        previous_network_requests=previous.network_requests if previous else [],
        popup_timeline=popup_timeline,
    )