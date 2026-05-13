"""
agents/visual_agent/nodes/preprocess.py

Builds structured text context for each vision detector.
No LLM calls — prepares DOM signals to send alongside the screenshot.
"""
from __future__ import annotations

import re

from agents.visual_agent.state import VisualAgentState


_AD_LABELS = re.compile(
    r"sponsored|ad\b|advertisement|promoted|partner|"
    r"paid\s+content|native\s+ad|affiliate|"
    r"recommended\s+for\s+you|top\s+picks|"
    r"editor.s\s+choice|best\s+seller|trending",
    re.IGNORECASE,
)

_INTERFERENCE_LABELS = re.compile(
    r"accept|agree|allow|confirm|yes|ok\b|"
    r"continue|proceed|enable|subscribe|sign\s+up|"
    r"get\s+started|install|download",
    re.IGNORECASE,
)

_DECLINE_LABELS = re.compile(
    r"decline|reject|no\s+thanks|cancel|close|"
    r"skip|dismiss|maybe\s+later|not\s+now|"
    r"manage\s+preferences|manage\s+settings|"
    r"reject\s+all|deny|refuse",
    re.IGNORECASE,
)


def preprocess_node(state: VisualAgentState) -> dict:
    """
    Build focused signal dicts for each visual detector.
    These are passed as text context alongside the screenshot.
    """
    links         = state.get("link_elements", [])
    buttons       = state.get("button_elements", [])
    overlays      = state.get("overlay_elements", [])
    text_elements = state.get("text_elements", [])
    forms         = state.get("forms", [])
    price_bboxes  = state.get("price_bounding_boxes", [])

    # ─────────────────────────────────────────────────────────
    # DISGUISED ADS SIGNALS
    # ─────────────────────────────────────────────────────────

    # Sponsored links flagged by scraper
    sponsored_links: list[dict] = []
    domain_mismatch_links: list[dict] = []
    for link in links:
        if link.get("is_sponsored"):
            sponsored_links.append({
                "text":     link.get("text", "")[:80],
                "href":     link.get("actual_href", "")[:100],
                "bbox":     link.get("bounding_box"),
            })
        if link.get("domain_mismatch"):
            domain_mismatch_links.append({
                "text":          link.get("text", "")[:80],
                "displayed_url": link.get("displayed_url", "")[:80],
                "actual_href":   link.get("actual_href", "")[:100],
            })

    # Text elements that mention ad/sponsored labels
    ad_label_texts: list[str] = []
    for t in text_elements:
        text = t.get("text", "")
        if _AD_LABELS.search(text) and len(text) < 150:
            ad_label_texts.append(
                f"[{t.get('tag','?')}|{t.get('location','?')}|"
                f"visible={t.get('is_visible')}|"
                f"fixed={t.get('is_in_fixed')}] {text[:100]}"
            )

    disguised_ads_signals = {
        "sponsored_link_count":       len(sponsored_links),
        "domain_mismatch_count":      len(domain_mismatch_links),
        "sponsored_links":            sponsored_links[:10],
        "domain_mismatch_links":      domain_mismatch_links[:10],
        "ad_label_texts":             ad_label_texts[:15],
        "has_sponsored_content":      len(sponsored_links) > 0,
        "has_domain_mismatches":      len(domain_mismatch_links) > 0,
    }

    # ─────────────────────────────────────────────────────────
    # INTERFACE INTERFERENCE SIGNALS
    # ─────────────────────────────────────────────────────────

    # Separate accept-type and decline-type buttons for comparison
    accept_buttons: list[dict] = []
    decline_buttons: list[dict] = []

    for btn in buttons:
        text = btn.get("text", "").strip()
        if not text:
            continue

        is_accept  = bool(_INTERFERENCE_LABELS.search(text))
        is_decline = bool(_DECLINE_LABELS.search(text))

        btn_summary = {
            "text":        text[:80],
            "bg_color":    btn.get("bg_color"),
            "text_color":  btn.get("text_color"),
            "font_size":   btn.get("font_size"),
            "is_in_modal": btn.get("is_in_modal"),
            "is_close":    btn.get("is_close_button"),
            "bbox":        btn.get("bounding_box"),
        }

        if is_accept and not is_decline:
            accept_buttons.append(btn_summary)
        elif is_decline or btn.get("is_close_button"):
            decline_buttons.append(btn_summary)

    # Overlay close button analysis
    overlays_without_close: list[dict] = []
    overlays_with_hidden_close: list[dict] = []
    for o in overlays:
        if not o.get("has_close_button"):
            overlays_without_close.append({
                "type":    o.get("overlay_type"),
                "coverage":o.get("viewport_coverage_pct", 0),
                "text":    o.get("text", "")[:100],
            })
        elif not o.get("close_button_prominent"):
            overlays_with_hidden_close.append({
                "type":    o.get("overlay_type"),
                "coverage":o.get("viewport_coverage_pct", 0),
                "text":    o.get("text", "")[:100],
            })

    # Pre-checked checkboxes
    pre_checked_fields: list[dict] = []
    for form in forms:
        for field in form.get("fields", []):
            if field.get("is_pre_checked") and field.get("input_type") == "checkbox":
                pre_checked_fields.append({
                    "label": field.get("label_text", "")[:80],
                    "value": field.get("value", "")[:40],
                    "hidden": field.get("is_hidden"),
                })

    # Interaction-blocking overlays
    blocking_overlays: list[dict] = []
    for o in overlays:
        if o.get("blocks_interaction"):
            blocking_overlays.append({
                "type":     o.get("overlay_type"),
                "coverage": o.get("viewport_coverage_pct", 0),
                "text":     o.get("text", "")[:100],
            })

    interface_interference_signals = {
        "accept_button_count":           len(accept_buttons),
        "decline_button_count":          len(decline_buttons),
        "accept_buttons":                accept_buttons[:10],
        "decline_buttons":               decline_buttons[:10],
        "has_asymmetry":                 len(accept_buttons) > 0 and len(decline_buttons) == 0,
        "overlays_without_close":        overlays_without_close[:5],
        "overlays_with_hidden_close":    overlays_with_hidden_close[:5],
        "pre_checked_fields":            pre_checked_fields[:10],
        "blocking_overlays":             blocking_overlays[:5],
        "total_overlays":                len(overlays),
        "has_blocking_overlays":         len(blocking_overlays) > 0,
        "has_overlays_without_close":    len(overlays_without_close) > 0,
        "has_pre_checked":               len(pre_checked_fields) > 0,
    }

    return {
        "disguised_ads_signals":            disguised_ads_signals,
        "interface_interference_signals":   interface_interference_signals,
    }