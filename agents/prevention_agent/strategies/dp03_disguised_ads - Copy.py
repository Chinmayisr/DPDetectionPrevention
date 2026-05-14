"""
agents/prevention_agent/strategies/dp03_disguised_ads.py
DP03 — Disguised Ads
Strategy:
  High confidence (>=0.8)  → ADD_BADGE with [SPONSORED] label (orange).
  Medium confidence (<0.8) → ADD_CLASS with dashed-orange border.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy

_BADGE_HTML_TEMPLATE = (
    '<span class="dg-ad-badge" style="'
    'display:inline-block;background:{bg};color:#fff;'
    'font-size:11px;font-weight:700;border-radius:3px;'
    'padding:2px 6px;margin-right:6px;font-family:sans-serif;'
    'vertical-align:middle;" '
    'title="Dark Guard AI flagged this as a possible disguised advertisement.">'
    '{label}</span>'
)


class DisguisedAdsStrategy(BaseStrategy):
    pattern_code = "DP03"
    pattern_name = "Disguised Ads"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []

        for ev in evidence:
            selector   = self._selector(ev)
            confidence = float(ev.get("confidence", 0.7))

            if confidence >= 0.8:
                # High confidence — inject [SPONSORED] badge at top of container
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "inject_element",
                    payload      = {
                        "html"    : _BADGE_HTML_TEMPLATE.format(
                            bg="#e65100", label="SPONSORED"
                        ),
                        "position": "prepend",
                    },
                    description = "Inject SPONSORED badge (high confidence disguised ad)",
                ))
            else:
                # Medium confidence — softer dashed border only
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "add_class",
                    payload      = {
                        "classes"        : ["dg-possible-ad"],
                        "style_override" : (
                            "border:2px dashed #e65100!important;"
                            "border-radius:4px!important;"
                        ),
                    },
                    description = "Dashed border: possible disguised ad (medium confidence)",
                ))

        return patches
