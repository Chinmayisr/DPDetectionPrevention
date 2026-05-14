"""
agents/prevention_agent/strategies/dp11_rogue_malicious.py
DP11 — Rogue / Malicious
Strategy:
  1. INJECT_ELEMENT — full-width permanent red warning banner (cannot be closed).
  2. INTERCEPT_CLICK — wrap each flagged element in a click confirmation dialog.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy


_PAGE_WARNING_HTML = (
    '<div id="dg-rogue-warning" style="'
    'position:fixed;top:0;left:0;width:100%;z-index:2147483647;'
    'background:#b71c1c;color:#fff;padding:10px 16px;'
    'font-family:sans-serif;font-size:14px;font-weight:700;'
    'box-shadow:0 2px 8px rgba(0,0,0,.4);">'
    '🚨 Dark Guard: Potentially malicious or deceptive elements detected on this page. '
    'Proceed with extreme caution.'
    '</div>'
)


class RogueMaliciousStrategy(BaseStrategy):
    pattern_code = "DP11"
    pattern_name = "Rogue and Malicious Content"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []

        # 1 — page-level permanent red banner (injected once)
        patches.append(self._raw(
            css_selector = "body",
            action       = "inject_element",
            payload      = {
                "html"    : _PAGE_WARNING_HTML,
                "position": "prepend",
            },
            description = "Permanent page-level malicious content warning",
        ))

        # 2 — click interceptor on each flagged element
        for ev in evidence:
            selector = self._selector(ev)
            reason   = ev.get("reason", "This element may trigger an unexpected action.")
            if selector in ("body", "html"):
                continue

            patches.append(self._raw(
                css_selector = selector,
                action       = "intercept_click",
                payload      = {
                    "warning_message": (
                        f"⚠ Dark Guard Warning: {reason}\n"
                        "Are you sure you want to proceed?"
                    ),
                    "confirm_label"  : "Continue anyway",
                    "cancel_label"   : "Go back",
                },
                description = f"Click interceptor on rogue element: {reason}",
            ))

        return patches
