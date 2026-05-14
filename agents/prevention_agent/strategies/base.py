"""
agents/prevention_agent/strategies/base.py
Abstract base class for all prevention strategies.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


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

    def _raw(
        self,
        css_selector : str,
        action       : str,
        payload      : dict,
        description  : str = "",
    ) -> dict:
        return {
            "css_selector": css_selector,
            "action"      : action,
            "payload"     : payload,
            "pattern_code": self.pattern_code,
            "pattern_name": self.pattern_name,
            "description" : description,
        }
