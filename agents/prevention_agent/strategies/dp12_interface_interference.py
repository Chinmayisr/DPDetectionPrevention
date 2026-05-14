"""
agents/prevention_agent/strategies/dp12_interface_interference.py
DP12 — Interface Interference (Visual Agent primary)
Strategy:
  1. ADD_CLASS — amplify undersized / low-contrast close buttons.
  2. ADD_CLASS — enforce visual parity between Accept/Reject options.
  3. INJECT_ELEMENT — magnified duplicate of tiny opt-out text.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy


_AMPLIFIED_TEXT_HTML_TEMPLATE = (
    '<div class="dg-amplified-text" style="'
    'background:#fff9c4;font-size:13px;padding:4px 8px;'
    'border-radius:3px;font-family:sans-serif;margin:4px 0;">'
    '🔍 Dark Guard (text enlarged): {text}'
    '</div>'
)


class InterfaceInterferenceStrategy(BaseStrategy):
    pattern_code = "DP12"
    pattern_name = "Interface Interference"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []

        for ev in evidence:
            selector = self._selector(ev)
            reason   = (ev.get("reason") or "").lower()
            text     = self._text(ev)

            is_close_button   = "close" in reason or "dismiss" in reason or "×" in text
            is_suppressed_btn = "reject" in reason or "decline" in reason or "opt-out" in reason
            is_tiny_text      = "tiny" in reason or "small" in reason or "font" in reason

            if is_close_button:
                # Amplify undersized or low-contrast close button
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "add_class",
                    payload      = {
                        "classes"        : ["dg-amplify-close"],
                        "style_override" : (
                            "min-width:44px!important;min-height:44px!important;"
                            "font-size:18px!important;opacity:1!important;"
                            "color:#000!important;background:#fff!important;"
                            "border:2px solid #000!important;border-radius:50%!important;"
                        ),
                    },
                    description = "Amplify undersized close button to WCAG tap-target size",
                ))

            elif is_suppressed_btn:
                # Enforce visual parity: reject button matches accept button weight
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "add_class",
                    payload      = {
                        "classes"        : ["dg-option-parity"],
                        "style_override" : (
                            "font-size:inherit!important;"
                            "padding:8px 16px!important;"
                            "font-weight:600!important;"
                            "opacity:1!important;"
                            "visibility:visible!important;"
                        ),
                    },
                    description = "Enforce visual parity on suppressed reject/decline button",
                ))

            elif is_tiny_text:
                # Inject magnified duplicate of tiny opt-out text below the element
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "inject_element",
                    payload      = {
                        "html"    : _AMPLIFIED_TEXT_HTML_TEMPLATE.format(text=text or "see above"),
                        "position": "after",
                    },
                    description = "Magnified duplicate of tiny opt-out text",
                ))

            else:
                # Generic: highlight the interfering element
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "add_badge",
                    payload      = {
                        "label"   : "⚠ UI",
                        "color"   : "#fff",
                        "bg_color": "#6a1b9a",
                        "title"   : f"Dark Guard: Interface interference detected. {ev.get('reason', '')}",
                    },
                    description = "Badge: interface interference",
                ))

        return patches
