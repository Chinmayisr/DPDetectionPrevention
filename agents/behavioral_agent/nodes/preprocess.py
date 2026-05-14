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

# ── Forced Action keyword patterns ────────────────────────────

_FORCED_GATE_KW = re.compile(
    r"you\s+must|must\s+sign\s+up|must\s+log\s+in|must\s+register|"
    r"required\s+to\s+sign|required\s+to\s+log|"
    r"sign\s+up\s+to\s+(continue|access|view|read|download|proceed)|"
    r"log\s+in\s+to\s+(continue|access|view|read|download|proceed)|"
    r"create\s+an?\s+account\s+to|register\s+to\s+(continue|access)|"
    r"login\s+required|sign.in\s+required|account\s+required|"
    r"members?\s+only|subscribers?\s+only|"
    r"install\s+(the\s+)?app\s+to|download\s+(the\s+)?app\s+to|"
    r"allow\s+notifications\s+to\s+(continue|access|proceed)|"
    r"accept\s+(all\s+)?cookies\s+to|"
    r"must\s+accept|agree\s+to\s+continue|"
    r"to\s+continue\s+(you\s+must|please\s+sign|please\s+log)|"
    r"guest\s+checkout\s+(not\s+)?available|"
    r"no\s+guest\s+checkout",
    re.IGNORECASE,
)

_FORCED_FORM_KW = re.compile(
    r"required|mandatory|must\s+complete|"
    r"phone\s+number\s+required|email\s+required|"
    r"verify\s+your\s+(phone|email|identity)",
    re.IGNORECASE,
)

_BLOCKING_OVERLAY_KW = re.compile(
    r"sign\s+up|log\s+in|login|register|create\s+account|"
    r"subscribe|join\s+now|get\s+started|"
    r"install\s+app|download\s+app|"
    r"allow\s+notifications|enable\s+notifications|"
    r"verify\s+age|age\s+gate|"
    r"enter\s+your\s+email|your\s+email\s+address",
    re.IGNORECASE,
)

_FINE_PRINT_LOCATIONS = {"footer", "body"}
_FINE_PRINT_TAGS = {"small", "span", "p"}

_SIMILARITY_THRESHOLD = 0.75
_NAGGING_COUNT_THRESHOLD = 2


# ── Safe string helper ────────────────────────────────────────

def _s(val) -> str:
    """
    Return val as a non-None string.

    Handles the case where a Pydantic Optional field (str | None)
    is serialised to Redis as JSON null and deserialised as a dict
    with key present but value None.

    dict.get("key", "") returns None when key exists with null value.
    (val or "") handles both None and the empty string case.
    """
    return val if isinstance(val, str) else ""


def _text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a[:200], b[:200]).ratio()


def preprocess_node(state: BehavioralAgentState) -> dict:
    """
    Build all six signal dicts from raw scraped data.
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
        (_s(i.get("name"))).lower().strip()
        for i in previous_cart
        if i.get("name")
    }
    new_items: list[dict] = []
    for item in current_cart:
        name = _s(item.get("name")).lower().strip()
        if name and name not in prev_item_names:
            new_items.append(item)

    auto_cart_mutation_count = len(auto_cart_mutations)
    # FIX: use _s() so None url values don't propagate
    cart_mutation_urls = [_s(r.get("url")) for r in auto_cart_mutations]

    cart_dom_mutations: list[dict] = []
    for m in mutations:
        # FIX: target_selector is str | None in DomMutation
        sel = _s(m.get("target_selector"))
        if sel and _CART_ENDPOINTS.search(sel):
            cart_dom_mutations.append(m)

    sneaking_text_signals: list[str] = []
    for t in text_elements:
        # FIX: use _s() — TextElement.text is required but Redis null is possible
        text = _s(t.get("text"))
        if re.search(
            r"included|pre.selected|automatically\s+added|"
            r"complimentary|free\s+add|protect\s+your|"
            r"we.ve\s+added|added\s+for\s+you",
            text, re.IGNORECASE
        ) and len(text) < 200:
            sneaking_text_signals.append(
                f"[{_s(t.get('location'))}] {text[:150]}"
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
        # FIX: all three fields use _s()
        text = _s(t.get("text"))
        tag  = _s(t.get("tag"))
        loc  = _s(t.get("location"))
        if _SUBSCRIPTION_KW.search(text) and len(text) < 300:
            entry = f"[{tag}|{loc}] {text[:150]}"
            subscription_kw_found.append(entry)
            if tag in _FINE_PRINT_TAGS or loc in _FINE_PRINT_LOCATIONS:
                fine_print_subscription.append(entry)

    ambiguous_cta: list[str] = []
    for b in buttons:
        # safe — already uses `or ""`
        btn_text = (_s(b.get("text"))).strip()
        if _SUBSCRIPTION_CTA.search(btn_text) and len(btn_text) < 100:
            ambiguous_cta.append(btn_text[:80])

    pre_checked_count = 0
    for form in forms:
        pre_checked_count += form.get("pre_checked_count", 0) or 0
        for field in form.get("fields", []):
            if field.get("input_type") == "checkbox" and field.get("is_pre_checked"):
                pre_checked_count += 1

    zero_price_cta = False
    for p in prices:
        amount = p.get("amount") or 0
        if 0 <= amount <= 1:
            zero_price_cta = True
            break

    subscription_api_calls: list[str] = []
    for req in network_requests:
        # FIX: url is required in NetworkRequest but could be null in Redis dict
        url = _s(req.get("url"))
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
    popup_groups: list[list[dict]] = []
    for entry in popup_timeline:
        # FIX: popup_timeline dicts have text built from overlay.get("text", "")
        # in the runner — but the overlay text itself could be None in Redis
        text = _s(entry.get("text"))[:200]
        placed = False
        for group in popup_groups:
            # FIX: same _s() protection for the group comparison
            group_text = _s(group[0].get("text"))[:200]
            if _text_similarity(text, group_text) >= _SIMILARITY_THRESHOLD:
                group.append(entry)
                placed = True
                break
        if not placed:
            popup_groups.append([entry])

    repeated_groups: list[dict] = []
    for group in popup_groups:
        if len(group) >= _NAGGING_COUNT_THRESHOLD:
            repeated_groups.append({
                "count":  len(group),
                # FIX: _s() on group text
                "text":   _s(group[0].get("text"))[:150],
                "pages":  [_s(e.get("url")) for e in group],
            })

    notification_requests: list[str] = []
    for t in text_elements:
        # FIX: _s() so _NOTIFICATION_KW.search never receives None
        text = _s(t.get("text"))
        if _NOTIFICATION_KW.search(text):
            notification_requests.append(
                f"[{_s(t.get('location'))}] {text[:100]}"
            )
    for o in current_overlays:
        # FIX: _s() on overlay text — OverlayElement.text is required but
        # Redis deserialisation can produce null
        overlay_text = _s(o.get("text"))
        if _NOTIFICATION_KW.search(overlay_text):
            notification_requests.append(
                f"[overlay] {overlay_text[:100]}"
            )

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
        # FIX: _s() on all three
        text = _s(t.get("text"))
        tag  = _s(t.get("tag"))
        loc  = _s(t.get("location"))

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

    price_anchoring: list[dict] = []
    for p in prices:
        if p.get("original_price") and p.get("amount"):
            orig    = p["original_price"]
            current = p["amount"]
            if orig > current:
                price_anchoring.append({
                    "original":    orig,
                    "current":     current,
                    "discount_pct": round(((orig - current) / orig) * 100, 1),
                    "text": _s(p.get("text"))[:80],
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
    high_traps:   list[dict] = []
    medium_traps: list[dict] = []

    for trap in redirect_traps:
        # FIX: LinkElement.actual_href is str | None — the original bug.
        # .get("actual_href", "") returns None when key exists with null value.
        # _s() converts None → "" safely.
        actual_href  = _s(trap.get("actual_href"))
        text         = _s(trap.get("text"))
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

    download_buttons: list[str] = []
    for b in buttons:
        btn_text = _s(b.get("text")).lower()
        # FIX: actual_href is Optional — _s() covers None
        href = _s(b.get("actual_href")) or _s(b.get("href"))
        if re.search(r"download|install|get\s+it|free\s+download", btn_text):
            if _ROGUE_REDIRECT_PATTERNS.search(href) or b.get("domain_mismatch"):
                download_buttons.append(
                    f"text='{_s(b.get('text'))[:60]}' href='{href[:80]}'"
                )

    injected_links: list[str] = []
    for m in mutations:
        if m.get("added_nodes_count", 0) > 0:
            # FIX: target_selector is str | None in DomMutation
            sel = _s(m.get("target_selector"))
            if sel and re.search(r"a\[|link|href|anchor", sel, re.IGNORECASE):
                injected_links.append(
                    f"selector={sel} at {m.get('timestamp_ms', 0):.0f}ms"
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

    # ─────────────────────────────────────────────────────────
    # 6. FORCED ACTION SIGNALS
    # ─────────────────────────────────────────────────────────

    # Gate language in text elements
    gate_text_signals: list[str] = []
    for t in text_elements:
        text = _s(t.get("text"))
        if _FORCED_GATE_KW.search(text) and len(text) < 300:
            gate_text_signals.append(
                f"[{_s(t.get('tag'))}|{_s(t.get('location'))}] {text[:200]}"
            )

    # Blocking overlays — overlays that gate access
    blocking_overlays: list[dict] = []
    for o in current_overlays:
        # FIX: _s() on overlay text before passing to regex
        overlay_text = _s(o.get("text"))
        is_blocking = (
            o.get("blocks_interaction", False) or
            (o.get("viewport_coverage_pct") or 0) > 40 or
            _BLOCKING_OVERLAY_KW.search(overlay_text)
        )
        if is_blocking:
            blocking_overlays.append({
                "type":       _s(o.get("overlay_type")),
                "coverage":   o.get("viewport_coverage_pct") or 0,
                "text":       overlay_text[:150],
                "has_close":  o.get("has_close_button", False),
                "blocks":     o.get("blocks_interaction", False),
                "autonomous": o.get("appeared_autonomously", False),
            })

    # Required form fields that shouldn't be required
    excessive_required_fields: list[dict] = []
    for form in forms:
        required_fields = [
            f for f in form.get("fields", [])
            if f.get("is_required") and not f.get("is_hidden")
        ]
        phone_required = any(
            re.search(
                r"phone|mobile|tel|cell",
                # FIX: both name and label_text are Optional in FormField
                _s(f.get("name")) + _s(f.get("label_text")),
                re.IGNORECASE,
            )
            for f in required_fields
        )
        consent_required = any(
            re.search(
                r"newsletter|marketing|promotions|offers",
                # FIX: label_text is Optional
                _s(f.get("label_text")),
                re.IGNORECASE,
            )
            and f.get("is_required")
            for f in form.get("fields", [])
        )
        if phone_required or consent_required:
            excessive_required_fields.append({
                "form_action":      _s(form.get("action")),
                "phone_required":   phone_required,
                "consent_required": consent_required,
                "field_count":      len(required_fields),
            })

    # Notification permission as gate
    notification_gate: list[str] = []
    for t in text_elements:
        text = _s(t.get("text"))
        if (
            _NOTIFICATION_KW.search(text) and
            re.search(r"to\s+(continue|access|proceed|use|view)", text, re.IGNORECASE)
        ):
            notification_gate.append(
                f"[{_s(t.get('location'))}] {text[:150]}"
            )

    # Guest checkout blocked detection
    guest_checkout_blocked: list[str] = []
    for t in text_elements:
        text = _s(t.get("text"))
        if re.search(
            r"guest\s+checkout\s+(not\s+)?(available|allowed|supported|possible)|"
            r"must\s+(create|have)\s+an?\s+account|"
            r"sign\s+in\s+to\s+checkout|login\s+to\s+checkout|"
            r"account\s+required\s+to\s+(purchase|buy|checkout)",
            text, re.IGNORECASE
        ):
            guest_checkout_blocked.append(
                f"[{_s(t.get('location'))}] {text[:150]}"
            )

    # Network requests triggered only after forced form submit
    blocked_navigation: list[str] = []
    for req in network_requests:
        # FIX: both url and method are required in NetworkRequest but
        # could be null in the Redis-deserialized dict
        url    = _s(req.get("url"))
        method = _s(req.get("method"))
        if (
            method == "POST" and
            re.search(
                r"register|signup|sign.up|login|log.in|auth|subscribe",
                url, re.IGNORECASE,
            ) and
            req.get("is_auto_triggered", False)
        ):
            blocked_navigation.append(url[:150])

    # Forced social login detection
    forced_social_login: list[str] = []
    for b in buttons:
        btn_text = _s(b.get("text")).strip()
        if re.search(
            r"continue\s+with\s+(google|facebook|apple|twitter|github)|"
            r"sign\s+in\s+with\s+(google|facebook|apple)|"
            r"log\s+in\s+with\s+(google|facebook|apple)",
            btn_text, re.IGNORECASE
        ):
            forced_social_login.append(btn_text[:80])

    forced_action_signals = {
        # Gate language
        "gate_text_signals":          gate_text_signals[:15],
        "gate_text_count":            len(gate_text_signals),

        # Blocking overlays
        "blocking_overlays":          blocking_overlays[:5],
        "blocking_overlay_count":     len(blocking_overlays),
        "has_blocking_overlay":       len(blocking_overlays) > 0,

        # Form analysis
        "excessive_required_fields":  excessive_required_fields[:5],
        "has_excessive_requirements": len(excessive_required_fields) > 0,

        # Specific forced action types
        "notification_gates":         notification_gate[:5],
        "has_notification_gate":      len(notification_gate) > 0,
        "guest_checkout_blocked":     guest_checkout_blocked[:5],
        "has_guest_checkout_blocked": len(guest_checkout_blocked) > 0,
        "forced_social_logins":       forced_social_login[:5],
        "has_forced_social_login":    len(forced_social_login) > 0,
        "blocked_navigation_requests":blocked_navigation[:5],

        # Overall assessment
        "total_forced_action_signals": (
            len(gate_text_signals) +
            len(blocking_overlays) +
            len(notification_gate) +
            len(guest_checkout_blocked)
        ),
        "is_likely_forced_action": (
            len(gate_text_signals) > 0 or
            len(blocking_overlays) > 0 or
            len(guest_checkout_blocked) > 0
        ),
    }

    return {
        "basket_sneaking_signals":   basket_sneaking_signals,
        "subscription_trap_signals": subscription_trap_signals,
        "nagging_signals":           nagging_signals,
        "saas_billing_signals":      saas_billing_signals,
        "rogue_malicious_signals":   rogue_malicious_signals,
        "forced_action_signals":     forced_action_signals,
    }