"""
agents/nlp_agent/nodes/preprocess.py
Builds focused text slices for each detector node.
Runs first, before any LLM calls.
"""
from __future__ import annotations

import re

from agents.nlp_agent.state import NLPAgentState


# Keywords that signal each pattern type
_URGENCY_KEYWORDS = re.compile(
    r"only|left|stock|hurry|limited|today|now|soon|deal|ends|flash|"
    r"sale|offer|fast|selling|minutes|hours|countdown|timer|expir|"
    r"viewing|watched|bought|popular|order\s+in",
    re.IGNORECASE,
)

_SHAMING_KEYWORDS = re.compile(
    r"no\s+thanks|no,\s+i|i\s+don.t\s+want|i\s+prefer\s+to|skip|"
    r"dismiss|decline|i.ll\s+pass|i\s+hate|i\s+don.t\s+need|"
    r"i\s+already|maybe\s+later|not\s+interested|i\s+don.t\s+care",
    re.IGNORECASE,
)

_ADS_KEYWORDS = re.compile(
    r"sponsored|recommended|promoted|featured|partner|ad\b|"
    r"advertisement|paid|top\s+picks|editor.s\s+choice|best\s+seller|"
    r"popular\s+now|trending|affiliate",
    re.IGNORECASE,
)

_TRICK_KEYWORDS = re.compile(
    r"uncheck|opt.out|opt\s+out|do\s+not\s+want|newsletter|"
    r"marketing|promotional|communications|share\s+my\s+data|"
    r"third.party|partners|agree|consent|unsubscribe",
    re.IGNORECASE,
)


def preprocess_node(state: NLPAgentState) -> dict:
    """
    Build focused text slices for each detector.
    Each slice contains the text_elements relevant to that pattern
    PLUS the general text_elements (as per user requirement).
    """
    text_elements: list[dict] = state.get("text_elements", [])
    buttons:  list[dict] = state.get("buttons", [])
    timers:   list[dict] = state.get("timers", [])
    overlays: list[dict] = state.get("overlays", [])
    links:    list[dict] = state.get("links", [])
    forms:    list[dict] = state.get("forms", [])

    # ── False Urgency slice ───────────────────────────────────
    urgency_slice: list[str] = []
    for t in text_elements:
        text = t.get("text", "")
        if _URGENCY_KEYWORDS.search(text):
            urgency_slice.append(
                f"[{t.get('location','?')}] {text}"
            )
    for timer in timers:
        urgency_slice.append(f"[timer] {timer.get('text', '')} | context: {timer.get('context','')}")
    for overlay in overlays:
        if _URGENCY_KEYWORDS.search(overlay.get("text", "")):
            urgency_slice.append(f"[overlay/{overlay.get('overlay_type','?')}] {overlay.get('text','')[:300]}")

    # ── Confirm Shaming slice ─────────────────────────────────
    shaming_slice: list[str] = []
    for t in text_elements:
        text = t.get("text", "")
        if _SHAMING_KEYWORDS.search(text):
            shaming_slice.append(f"[{t.get('location','?')}] {text}")
    for btn in buttons:
        btn_text = btn.get("text", "")
        if btn_text and (btn.get("is_in_modal") or btn.get("is_close_button")):
            shaming_slice.append(
                f"[button|modal={btn.get('is_in_modal')}|close={btn.get('is_close_button')}] {btn_text[:200]}"
            )
    for overlay in overlays:
        shaming_slice.append(
            f"[overlay/{overlay.get('overlay_type','?')}] {overlay.get('text','')[:300]}"
        )

    # ── Disguised Ads slice ───────────────────────────────────
    ads_slice: list[str] = []
    for t in text_elements:
        text = t.get("text", "")
        if _ADS_KEYWORDS.search(text):
            ads_slice.append(f"[{t.get('location','?')}] {text}")
    for link in links:
        if link.get("is_sponsored") or link.get("domain_mismatch"):
            ads_slice.append(
                f"[link|sponsored={link.get('is_sponsored')}|mismatch={link.get('domain_mismatch')}] "
                f"text='{link.get('text','')}' href='{link.get('actual_href','')[:100]}'"
            )

    # ── Trick Question slice ──────────────────────────────────
    trick_slice: list[str] = []
    for t in text_elements:
        text = t.get("text", "")
        loc  = t.get("location", "")
        if _TRICK_KEYWORDS.search(text) or loc == "form":
            trick_slice.append(f"[{loc}] {text}")
    for form in forms:
        for field in form.get("fields", []):
            if field.get("input_type") == "checkbox":
                trick_slice.append(
                    f"[checkbox|pre_checked={field.get('is_pre_checked')}|hidden={field.get('is_hidden')}] "
                    f"label='{field.get('label_text','')}'  value='{field.get('value','')}'"
                )
        if form.get("has_hidden_consent"):
            trick_slice.append(f"[form|hidden_consent=True] action={form.get('action','')}")
        if form.get("pre_checked_count", 0) > 0:
            trick_slice.append(f"[form|pre_checked_count={form['pre_checked_count']}]")

    return {
        "urgency_slice":         urgency_slice[:150],
        "confirm_shaming_slice": shaming_slice[:150],
        "disguised_ads_slice":   ads_slice[:150],
        "trick_question_slice":  trick_slice[:150],
    }