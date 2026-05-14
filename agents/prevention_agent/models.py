"""
agents/prevention_agent/models.py
─────────────────────────────────────────────────────────────────
Pydantic models for the Prevention Agent output.

PatchInstruction  — a single DOM mutation the content script will apply.
PreventionResult  — the full output of the Prevention Agent for one scan.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Action Types ──────────────────────────────────────────────

class PatchAction(str, Enum):
    REPLACE_TEXT      = "replace_text"      # swap text content of an element
    INJECT_ELEMENT    = "inject_element"    # insert a new HTML element
    ADD_CLASS         = "add_class"         # add CSS class(es) to element
    ADD_BADGE         = "add_badge"         # inject a small label badge
    INTERCEPT_CLICK   = "intercept_click"   # wrap element in a confirmation dialog
    UNCHECK           = "uncheck"           # uncheck a pre-checked checkbox


# ── Priority constants (lower = applied first) ────────────────
# Safety-critical patches (DP11) run before cosmetic ones (DP03).

PRIORITY = {
    "DP11": 1,   # Rogue/Malicious — hard warning injected first
    "DP13": 2,   # Forced Action — gate bypass
    "DP07": 3,   # Basket Sneaking — cart audit
    "DP08": 4,   # Subscription Trap — billing notice
    "DP05": 5,   # Drip Pricing — fee panel
    "DP06": 5,   # Bait & Switch — price mismatch banner
    "DP01": 6,   # False Urgency — timer neutralize
    "DP02": 6,   # Confirm Shaming — text rewrite
    "DP04": 6,   # Trick Question — uncheck + tooltip
    "DP12": 7,   # Interface Interference — UI normalise
    "DP09": 8,   # Nagging — suppress popup
    "DP10": 8,   # SaaS Billing — clarification tooltip
    "DP03": 9,   # Disguised Ads — badge
}


# ── Core patch model ──────────────────────────────────────────

class PatchInstruction(BaseModel):
    """
    One atomic DOM mutation to be executed by the content script.

    Payload shapes by action:
    ─────────────────────────────────────────────────────────────
    replace_text     : { "new_text": str }
    inject_element   : { "html": str, "position": "before"|"after"|"prepend"|"append" }
    add_class        : { "classes": list[str], "style_override": str | None }
    add_badge        : { "label": str, "color": str, "bg_color": str, "title": str }
    intercept_click  : { "warning_message": str, "confirm_label": str, "cancel_label": str }
    uncheck          : { "enforce_on_mutation": bool }
    """
    css_selector  : str
    action        : PatchAction
    payload       : dict[str, Any]
    pattern_code  : str                  # e.g. "DP01"
    pattern_name  : str
    description   : str   = ""
    priority      : int   = 5           # lower = applied first by content script


# ── Final agent output ────────────────────────────────────────

class PreventionResult(BaseModel):
    scrape_id            : str
    session_id           : str
    url                  : str
    patch_instructions   : list[PatchInstruction]
    patterns_addressed   : list[str]          # list of pattern codes handled
    total_patches        : int
    prevention_duration_ms: int
    prevented_at         : datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
