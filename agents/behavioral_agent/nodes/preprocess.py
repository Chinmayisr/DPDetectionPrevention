"""
agents/behavioral_agent/nodes/preprocess.py

Computes all behavioral signals before any LLM call.
Zero LLM usage here — pure Python analysis.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from agents.behavioral_agent.state import BehavioralAgentState


# ── Keyword patterns ──────────────────────────────────────────

_SUBSCRIPTION_KW = re.compile(
    r"per\s+month|per\s+year|\/mo|\/month|\/yr|\/year|"
    r"auto.renew|auto\s+renew|recurring|subscription|"
    r"billed\s+(monthly|annually|yearly|quarterly)|"
    r"cancel\s+anytime|free\s+trial|trial\s+ends|"
    r"then\s+\$|after\s+trial|introductory|"
    r"negative\s+option|membership\s+fee|"
    r"renews\s+at|renewal\s+price",
    re.IGNORECASE,
)

_SUBSCRIPTION_CTA = re.compile(
    r"get\s+started|start\s+free|try\s+free|claim\s+offer|"
    r"activate|unlock|join\s+now|sign\s+up\s+free|"
    r"continue\s+for\s+free|access\s+now",
    re.IGNORECASE,
)

_SAAS_BILLING_KW = re.compile(
    r"billed\s+annually|billed\s+yearly|annual\s+plan|"
    r"per\s+seat|per\s+user|per\s+agent|"
    r"save\s+\d+%|introductory\s+price|"
    r"starting\s+at|as\s+low\s+as|"
    r"monthly\s+equivalent|\/mo\s+billed|"
    r"price\s+increase|escalat",
    re.IGNORECASE,
)

_NOTIFICATION_KW = re.compile(
    r"allow\s+notifications|enable\s+notifications|"
    r"turn\s+on\s+notifications|push\s+notifications|"
    r"stay\s+updated|get\s+alerts|notify\s+me",
    re.IGNORECASE,
)

_ROGUE_REDIRECT_PATTERNS = re.compile(
    r"/go/|/click/|/redirect/|/out/|out\.php|"
    r"click\.php|go\.php|track\.|ad\.doubleclick|"
    r"googleadservices|pagead|bannerclick",
    re.IGNORECASE,
)

_CART_ENDPOINTS = re.compile(
    r"/cart|/basket|/bag|add.to.cart|addtocart|"
    r"line.items|lineItems|/order/add",
    re.IGNORECASE,
)

_FINE_PRINT_LOCATIONS = {"footer", "body"}
_FINE_PRINT_TAGS = {"small", "span", "p"}

_SIMILARITY_THRESHOLD = 0.75   # 75% text similarity = "same" popup
_NAGGING_COUNT_THRESHOLD = 2   # 2+ identical popups = nagging


def _text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a[:200], b[:200]).ratio()


def preprocess_node(state: BehavioralAgentState) -> dict:
    """
    Build all five signal dicts from raw scraped data.
    No LLM calls — pure deterministic analysis.
    """

    text_elements         = state.get("text_elements", [])
    buttons               = state.get("buttons", [])
    forms                 = state.get("forms", [])
    prices                = state.get("prices", [])
    links                 = state.get("links", [])
    current_cart          = state.get("current_cart_items", [])
    previous_cart         = state.get("previous_cart_items", [])
    auto_cart_mutations   = state.get("current_auto_cart_mutations", [])
    current_overlays      = state.get("current_overlays", [])
    popup_timeline        = state.get("popup_timeline", [])
    mutations             = state.get("current_mutations", [])
    network_requests      = state.get("current_network_requests", [])
    redirect_traps        = state.get("redirect_traps", [])
    auto_popup_count      = state.get("auto_popup_count", 0)

    # ─────────────────────────────────────────────────────────
    # 1. BASKET SNEAKING SIGNALS
    # ─────────────────────────────────────────────────────────
    prev_item_names = {
        (i.get("name") or "").lower().strip()
        for i in previous_cart
        if i.get("name")
    }
    new_items: list[dict] = []
    for item in current_cart:
        name = (item.get("name") or "").lower().strip()
        if name and name not in prev_item_names:
            new_items.append(item)

    # Cart auto-mutations from network layer
    auto_cart_mutation_count = len(auto_cart_mutations)
    cart_mutation_urls = [r.get("url", "") for r in auto_cart_mutations]

    # DOM mutations that touched cart-like elements
    cart_dom_mutations: list[dict] = []
    for m in mutations:
        sel = m.get("target_selector", "")
        if sel and _CART_ENDPOINTS.search(sel):
            cart_dom_mutations.append(m)

    # Text signals near add-on descriptions
    sneaking_text_signals: list[str] = []
    for t in text_elements:
        text = t.get("text", "")
        if re.search(
            r"included|pre.selected|automatically\s+added|"
            r"complimentary|free\s+add|protect\s+your|"
            r"we.ve\s+added|added\s+for\s+you",
            text, re.IGNORECASE
        ) and len(text) < 200:
            sneaking_text_signals.append(
                f"[{t.get('location','?')}] {text[:150]}"
            )

    basket_sneaking_signals = {
        "new_items_in_cart":        new_items,
        "new_item_count":           len(new_items),
        "auto_cart_mutation_count": auto_cart_mutation_count,
        "cart_mutation_urls":       cart_mutation_urls,
        "cart_dom_mutations_count": len(cart_dom_mutations),
        "sneaking_text_signals":    sneaking_text_signals[:10],
        "has_auto_mutations":       auto_cart_mutation_count > 0,
        "has_new_items":            len(new_items) > 0,
    }

    # ─────────────────────────────────────────────────────────
    # 2. SUBSCRIPTION TRAP SIGNALS
    # ─────────────────────────────────────────────────────────
    subscription_kw_found: list[str] = []
    fine_print_subscription: list[str] = []

    for t in text_elements:
        text = t.get("text", "")
        tag  = t.get("tag", "")
        loc  = t.get("location", "")
        if _SUBSCRIPTION_KW.search(text) and len(text) < 300:
            entry = f"[{tag}|{loc}] {text[:150]}"
            subscription_kw_found.append(entry)
            # Fine print = small tag or footer location
            if tag in _FINE_PRINT_TAGS or loc in _FINE_PRINT_LOCATIONS:
                fine_print_subscription.append(entry)

    # Check CTA buttons for ambiguous text
    ambiguous_cta: list[str] = []
    for b in buttons:
        btn_text = (b.get("text") or "").strip()
        if _SUBSCRIPTION_CTA.search(btn_text) and len(btn_text) < 100:
            ambiguous_cta.append(btn_text[:80])

    # Pre-checked consent checkboxes
    pre_checked_count = 0
    for form in forms:
        pre_checked_count += form.get("pre_checked_count", 0)
        for field in form.get("fields", []):
            if field.get("input_type") == "checkbox" and field.get("is_pre_checked"):
                pre_checked_count += 1

    # Is the total zero or near-zero (free trial)?
    zero_price_cta = False
    for p in prices:
        amount = p.get("amount") or 0
        if 0 <= amount <= 1:
            zero_price_cta = True
            break

    # Network calls to subscription endpoints
    subscription_api_calls: list[str] = []
    for req in network_requests:
        url = req.get("url", "")
        if re.search(
            r"subscribe|subscription|billing|checkout|payment|trial",
            url, re.IGNORECASE
        ) and req.get("is_auto_triggered"):
            subscription_api_calls.append(url[:150])

    subscription_trap_signals = {
        "subscription_kw_found":    subscription_kw_found[:20],
        "fine_print_subscription":  fine_print_subscription[:10],
        "ambiguous_cta_texts":      ambiguous_cta[:10],
        "pre_checked_consent_count":pre_checked_count,
        "is_zero_price_cta":        zero_price_cta,
        "subscription_api_calls":   subscription_api_calls[:10],
        "total_subscription_signals": len(subscription_kw_found),
        "has_fine_print_terms":     len(fine_print_subscription) > 0,
    }

    # ─────────────────────────────────────────────────────────
    # 3. NAGGING SIGNALS
    # ─────────────────────────────────────────────────────────

    # Group popup_timeline by text similarity
    popup_groups: list[list[dict]] = []
    for entry in popup_timeline:
        text = entry.get("text", "")[:200]
        placed = False
        for group in popup_groups:
            if _text_similarity(text, group[0].get("text", "")[:200]) >= _SIMILARITY_THRESHOLD:
                group.append(entry)
                placed = True
                break
        if not placed:
            popup_groups.append([entry])

    # Find groups that appeared more than threshold times
    repeated_groups: list[dict] = []
    for group in popup_groups:
        if len(group) >= _NAGGING_COUNT_THRESHOLD:
            repeated_groups.append({
                "count":  len(group),
                "text":   group[0].get("text", "")[:150],
                "pages":  [e.get("url", "") for e in group],
            })

    # Notification request detection
    notification_requests: list[str] = []
    for t in text_elements:
        if _NOTIFICATION_KW.search(t.get("text", "")):
            notification_requests.append(
                f"[{t.get('location','?')}] {t.get('text','')[:100]}"
            )
    for o in current_overlays:
        if _NOTIFICATION_KW.search(o.get("text", "")):
            notification_requests.append(
                f"[overlay] {o.get('text','')[:100]}"
            )

    # Total autonomous popups across session
    total_autonomous = sum(
        1 for e in popup_timeline
        if e.get("autonomous", False)
    )

    nagging_signals = {
        "repeated_popup_groups":    repeated_groups,
        "repeated_popup_count":     len(repeated_groups),
        "max_repeat_count":         max((g["count"] for g in repeated_groups), default=0),
        "total_session_popups":     len(popup_timeline),
        "total_autonomous_popups":  total_autonomous,
        "auto_popup_count_current": auto_popup_count,
        "notification_requests":    notification_requests[:10],
        "notification_request_found": len(notification_requests) > 0,
        "is_nagging":               len(repeated_groups) > 0,
    }

    # ─────────────────────────────────────────────────────────
    # 4. SAAS BILLING SIGNALS
    # ─────────────────────────────────────────────────────────

    saas_kw_found: list[str] = []
    annual_billed_as_monthly: list[str] = []
    per_seat_signals: list[str] = []
    intro_price_signals: list[str] = []

    for t in text_elements:
        text = t.get("text", "")
        tag  = t.get("tag", "")
        loc  = t.get("location", "")

        if not _SAAS_BILLING_KW.search(text):
            continue
        if len(text) > 300:
            continue

        entry = f"[{tag}|{loc}] {text[:150]}"
        saas_kw_found.append(entry)

        if re.search(r"billed\s+(annually|yearly)|annual\s+plan", text, re.IGNORECASE):
            annual_billed_as_monthly.append(entry)

        if re.search(r"per\s+(seat|user|agent|member)", text, re.IGNORECASE):
            per_seat_signals.append(entry)

        if re.search(r"introductory|then\s+\$|after\s+\d+|price\s+increase", text, re.IGNORECASE):
            intro_price_signals.append(entry)

    # Price anchoring: look for crossed-out prices (original_price present)
    price_anchoring: list[dict] = []
    for p in prices:
        if p.get("original_price") and p.get("amount"):
            orig = p["original_price"]
            current = p["amount"]
            if orig > current:
                price_anchoring.append({
                    "original": orig,
                    "current":  current,
                    "discount_pct": round(((orig - current) / orig) * 100, 1),
                    "text": p.get("text", "")[:80],
                })

    saas_billing_signals = {
        "saas_kw_found":              saas_kw_found[:20],
        "annual_billed_as_monthly":   annual_billed_as_monthly[:10],
        "per_seat_signals":           per_seat_signals[:10],
        "intro_price_signals":        intro_price_signals[:10],
        "price_anchoring":            price_anchoring[:5],
        "total_saas_signals":         len(saas_kw_found),
        "billing_period_mismatch":    len(annual_billed_as_monthly) > 0,
        "has_per_seat_hidden":        len(per_seat_signals) > 0,
        "has_intro_price":            len(intro_price_signals) > 0,
        "has_price_anchoring":        len(price_anchoring) > 0,
    }

    # ─────────────────────────────────────────────────────────
    # 5. ROGUE / MALICIOUS SIGNALS
    # ─────────────────────────────────────────────────────────

    # Classify redirect traps by severity
    high_traps:   list[dict] = []
    medium_traps: list[dict] = []

    for trap in redirect_traps:
        actual_href  = trap.get("actual_href", "")
        text         = trap.get("text", "")
        is_sponsored = trap.get("is_sponsored", False)
        mismatch     = trap.get("domain_mismatch", False)

        severity = "low"
        if _ROGUE_REDIRECT_PATTERNS.search(actual_href):
            severity = "high"
        elif mismatch and re.search(
            r"download|install|click\s+here|get\s+it|free",
            text, re.IGNORECASE
        ):
            severity = "high"
        elif mismatch or is_sponsored:
            severity = "medium"

        entry = {
            "text":         text[:100],
            "actual_href":  actual_href[:150],
            "severity":     severity,
            "is_sponsored": is_sponsored,
            "mismatch":     mismatch,
        }
        if severity == "high":
            high_traps.append(entry)
        elif severity == "medium":
            medium_traps.append(entry)

    # Suspicious download buttons
    download_buttons: list[str] = []
    for b in buttons:
        btn_text = (b.get("text") or "").lower()
        href = (b.get("actual_href") or b.get("href") or "")
        if re.search(r"download|install|get\s+it|free\s+download", btn_text):
            if _ROGUE_REDIRECT_PATTERNS.search(href) or b.get("domain_mismatch"):
                download_buttons.append(
                    f"text='{b.get('text','')[:60]}' href='{href[:80]}'"
                )

    # JS-injected links (added via DOM mutation after page load)
    injected_links: list[str] = []
    for m in mutations:
        if m.get("added_nodes_count", 0) > 0:
            sel = m.get("target_selector", "")
            if sel and re.search(r"a\[|link|href|anchor", sel, re.IGNORECASE):
                injected_links.append(
                    f"selector={sel} at {m.get('timestamp_ms',0):.0f}ms"
                )

    rogue_malicious_signals = {
        "high_severity_traps":    high_traps[:10],
        "medium_severity_traps":  medium_traps[:10],
        "high_trap_count":        len(high_traps),
        "medium_trap_count":      len(medium_traps),
        "total_redirect_traps":   len(redirect_traps),
        "suspicious_download_buttons": download_buttons[:5],
        "injected_link_count":    len(injected_links),
        "injected_links":         injected_links[:5],
        "has_high_severity":      len(high_traps) > 0,
    }

    return {
        "basket_sneaking_signals":   basket_sneaking_signals,
        "subscription_trap_signals": subscription_trap_signals,
        "nagging_signals":           nagging_signals,
        "saas_billing_signals":      saas_billing_signals,
        "rogue_malicious_signals":   rogue_malicious_signals,
    }