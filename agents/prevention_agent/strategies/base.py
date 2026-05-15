"""
agents/prevention_agent/strategies/base.py
Abstract base class for all prevention strategies.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

# Selectors that are too broad to target a meaningful element.
# When a strategy falls back to one of these, the evidence text is
# embedded as text_hint so the content script can locate the real element.
_BROAD_SELECTORS: frozenset[str] = frozenset({
    "body", "html", "head", "main", "#root", "#app",
    "body > *", "div", "section", "article",
})


class BaseStrategy(ABC):
    """
    Every strategy receives:
      evidence   : list of evidence dicts from the detection agent
                   Each has: text, location, reason, css_selector (optional)
      enrichment : additional data for this pattern from Redis
                   (pricing_breakdown, session_cart_data, behavioral_data, visual_data)

    Returns a list of raw patch dicts consumed by patch_builder.build_patch().
    """

    pattern_code: str = ""
    pattern_name: str = ""

    @abstractmethod
    async def build_patches(
        self,
        evidence   : list[dict[str, Any]],
        enrichment : dict[str, Any],
    ) -> list[dict[str, Any]]:
        ...

    # ── shared helpers ────────────────────────────────────────

    def _selector(self, ev: dict, fallback: str = "body") -> str:
        return ev.get("css_selector") or fallback

    def _text(self, ev: dict) -> str:
        return (ev.get("text") or "").strip()

    def _is_broad(self, selector: str) -> bool:
        return selector.strip().lower() in _BROAD_SELECTORS

    def _raw(
        self,
        css_selector : str,
        action       : str,
        payload      : dict,
        description  : str = "",
        text_hint    : str = "",
    ) -> dict:
        """
        Build a raw patch dict.

        If css_selector is a broad fallback (e.g. "body") and text_hint is
        provided, text_hint is embedded in the payload so the content script
        can locate the real DOM element by its text content instead of
        targeting the entire page body.
        """
        merged_payload = dict(payload)
        if text_hint and self._is_broad(css_selector):
            merged_payload["text_hint"] = text_hint

        return {
            "css_selector": css_selector,
            "action"      : action,
            "payload"     : merged_payload,
            "pattern_code": self.pattern_code,
            "pattern_name": self.pattern_name,
            "description" : description,
        }