"""
agents/pricing_agent/nodes/preprocess.py

Performs ALL arithmetic before any LLM call.
The LLM receives structured signals, not raw numbers to calculate.
"""
from __future__ import annotations

import re

from agents.pricing_agent.state import PricingAgentState


# Labels that strongly indicate drip pricing fees
_DRIP_LABELS = re.compile(
    r"service\s+fee|convenience\s+fee|platform\s+fee|processing\s+fee|"
    r"handling\s+fee|booking\s+fee|transaction\s+fee|surcharge|"
    r"packaging\s+fee|rain\s+fee|peak\s+fee|resort\s+fee|"
    r"facility\s+fee|cleaning\s+fee|insurance|protection\s+plan|"
    r"priority\s+fee|delivery\s+insurance",
    re.IGNORECASE,
)

# Text patterns on page that signal bait and switch
_BAIT_SWITCH_TEXT = re.compile(
    r"price\s+(has\s+)?(changed|updated|increased)|"
    r"price\s+change|deal\s+expired|offer\s+expired|"
    r"no\s+longer\s+available\s+at|limited\s+time\s+price|"
    r"price\s+may\s+vary|adjusted\s+price",
    re.IGNORECASE,
)

_VARIANCE_THRESHOLD_PCT  = 1.0   # ignore variances below 1% (rounding)
_DRIP_GAP_THRESHOLD_PCT  = 3.0   # flag price gap > 3% of subtotal
_DRIP_GAP_THRESHOLD_ABS  = 30.0  # or absolute gap > ₹30/$1.50


def preprocess_node(state: PricingAgentState) -> dict:
    """
    Build structured drip_pricing_signals and bait_switch_signals
    from raw scraped data — all arithmetic done here, zero LLM calls.
    """

    # ── DRIP PRICING SIGNALS ──────────────────────────────────
    supplemental: list[dict] = state.get("supplemental_charges", [])
    displayed_total:   float | None = state.get("displayed_total")
    computed_subtotal: float | None = state.get("computed_subtotal")
    price_gap:         float | None = state.get("price_gap")
    text_elements: list[dict]  = state.get("text_elements", [])

    suspicious_charges: list[dict] = []
    total_hidden_amount: float = 0.0
    pre_selected_amount: float = 0.0

    for charge in supplemental:
        label  = charge.get("label", "")
        amount = charge.get("amount") or 0.0
        is_pre = charge.get("is_pre_selected", False)

        is_suspicious = (
            _DRIP_LABELS.search(label) or
            is_pre or
            (amount > 0 and not charge.get("is_optional", True))
        )

        if is_suspicious:
            suspicious_charges.append({
                "label":        label,
                "amount":       round(amount, 2),
                "is_pre_selected": is_pre,
                "is_optional":  charge.get("is_optional", True),
            })
            total_hidden_amount += amount
            if is_pre:
                pre_selected_amount += amount

    # Price gap analysis
    gap_pct: float = 0.0
    gap_is_significant = False
    if computed_subtotal and computed_subtotal > 0 and price_gap is not None:
        gap_pct = round((abs(price_gap) / computed_subtotal) * 100, 2)
        gap_is_significant = (
            gap_pct > _DRIP_GAP_THRESHOLD_PCT or
            abs(price_gap) > _DRIP_GAP_THRESHOLD_ABS
        )

    # Scan text elements for fee-related language
    fee_text_signals: list[str] = []
    for t in text_elements:
        text = t.get("text", "")
        if _DRIP_LABELS.search(text) and len(text) < 200:
            fee_text_signals.append(
                f"[{t.get('location','?')}] {text[:150]}"
            )

    drip_pricing_signals = {
        "suspicious_charges":   suspicious_charges,
        "total_hidden_amount":  round(total_hidden_amount, 2),
        "pre_selected_amount":  round(pre_selected_amount, 2),
        "displayed_total":      displayed_total,
        "computed_subtotal":    computed_subtotal,
        "price_gap":            round(price_gap, 2) if price_gap else 0.0,
        "price_gap_pct":        gap_pct,
        "gap_is_significant":   gap_is_significant,
        "fee_text_signals":     fee_text_signals[:20],
        "has_pre_selected_charges": pre_selected_amount > 0,
        "suspicious_charge_count":  len(suspicious_charges),
    }

    # ── BAIT AND SWITCH SIGNALS ───────────────────────────────
    price_diffs: list[dict] = state.get("price_diffs", [])
    previous_url: str | None = state.get("previous_url")
    current_url:  str        = state.get("current_url", "")

    significant_variances: list[dict] = []
    max_variance_pct: float = 0.0
    total_overcharge:  float = 0.0

    for diff in price_diffs:
        variance     = diff.get("variance", 0.0) or 0.0
        variance_pct = diff.get("variance_pct", 0.0) or 0.0

        # Only flag increases (positive variance = more expensive in cart)
        if variance <= 0:
            continue
        if abs(variance_pct) < _VARIANCE_THRESHOLD_PCT:
            continue

        significant_variances.append({
            "item":               diff.get("item", "Unknown item"),
            "price_product_page": diff.get("price_on_previous_page"),
            "price_cart":         diff.get("price_on_current_page"),
            "variance_abs":       round(variance, 2),
            "variance_pct":       round(variance_pct, 2),
        })
        total_overcharge += variance
        if abs(variance_pct) > max_variance_pct:
            max_variance_pct = abs(variance_pct)

    # Scan text elements for bait-switch language
    bait_text_signals: list[str] = []
    for t in text_elements:
        text = t.get("text", "")
        if _BAIT_SWITCH_TEXT.search(text) and len(text) < 300:
            bait_text_signals.append(
                f"[{t.get('location','?')}] {text[:200]}"
            )

    bait_switch_signals = {
        "significant_variances":    significant_variances,
        "variance_count":           len(significant_variances),
        "max_variance_pct":         round(max_variance_pct, 2),
        "total_overcharge":         round(total_overcharge, 2),
        "has_previous_page":        previous_url is not None,
        "previous_url":             previous_url or "N/A",
        "current_url":              current_url,
        "bait_text_signals":        bait_text_signals[:10],
        "has_bait_switch_language": len(bait_text_signals) > 0,
    }

    return {
        "drip_pricing_signals": drip_pricing_signals,
        "bait_switch_signals":  bait_switch_signals,
    }