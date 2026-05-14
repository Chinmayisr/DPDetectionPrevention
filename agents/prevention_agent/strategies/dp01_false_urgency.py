"""
agents/prevention_agent/strategies/dp01_false_urgency.py
─────────────────────────────────────────────────────────
DP01 — False Urgency

Strategy:
  1. INJECT_ELEMENT — overlay a neutralizing notice above the urgency element.
  2. REPLACE_TEXT   — for stock scarcity text, rewrite to a neutral form.
  3. ADD_BADGE      — attach an info badge beside each flagged element.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy

_NEUTRALIZE_HTML = (
    '<div class="dg-urgency-notice" style="'
    'background:#fff8e1;border-left:4px solid #ffa000;'
    'padding:8px 12px;margin:4px 0;font-size:13px;color:#5d4037;'
    'border-radius:4px;font-family:sans-serif;">'
    '⚠ Dark Guard: This timer or availability claim may not reflect '
    'a real deadline. Take your time making this decision.'
    '</div>'
)


class FalseUrgencyStrategy(BaseStrategy):
    pattern_code = "DP01"
    pattern_name = "False Urgency"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []

        for ev in evidence:
            selector = self._selector(ev)
            text     = self._text(ev)
            reason   = ev.get("reason", "")

            # 1 — inject neutralizing notice before the urgency element
            patches.append(self._raw(
                css_selector = selector,
                action       = "inject_element",
                payload      = {
                    "html"    : _NEUTRALIZE_HTML,
                    "position": "before",
                },
                description  = f"Neutralize urgency: {reason}",
            ))

            # 2 — if text looks like stock scarcity, rewrite it
            lower = text.lower()
            if any(kw in lower for kw in ("only", "left", "remaining", "hurry", "limited")):
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "replace_text",
                    payload      = {"new_text": "Limited availability may apply"},
                    description  = "Rewrite stock scarcity claim to neutral form",
                ))

            # 3 — add info badge
            patches.append(self._raw(
                css_selector = selector,
                action       = "add_badge",
                payload      = {
                    "label"   : "ℹ Urgency",
                    "color"   : "#fff",
                    "bg_color": "#ffa000",
                    "title"   : "Dark Guard: This urgency claim may be artificial.",
                },
                description  = "Badge: urgency flag",
            ))

        return patches
