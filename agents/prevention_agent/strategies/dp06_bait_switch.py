"""
agents/prevention_agent/strategies/dp06_bait_switch.py
DP06 — Bait and Switch
Strategy:
  INJECT_ELEMENT — price mismatch banner directly above the checkout price,
  showing original advertised price vs current checkout price.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy


def _mismatch_banner_html(original: str, current: str, original_url: str = "") -> str:
    link_html = (
        f' <a href="{original_url}" style="color:#0d47a1;font-size:12px;" '
        f'target="_blank">[View original listing]</a>'
        if original_url else ""
    )
    return (
        '<div class="dg-price-mismatch" style="'
        'border-left:4px solid #c62828;background:#ffebee;'
        'padding:8px 12px;margin-bottom:6px;font-family:sans-serif;font-size:13px;">'
        f'⚠ <strong>Dark Guard:</strong> Price changed. '
        f'You were shown <strong>{original}</strong> on the product page. '
        f'Checkout price: <strong style="color:#c62828;">{current}</strong>.'
        f'{link_html}'
        '</div>'
    )


def _substitution_banner_html(original_name: str) -> str:
    return (
        '<div class="dg-product-substitution" style="'
        'border-left:4px solid #6a1b9a;background:#f3e5f5;'
        'padding:8px 12px;margin-bottom:6px;font-family:sans-serif;font-size:13px;">'
        f'⚠ <strong>Dark Guard:</strong> This item may differ from what was advertised. '
        f'Advertised product: <strong>{original_name}</strong>.'
        '</div>'
    )


class BaitSwitchStrategy(BaseStrategy):
    pattern_code = "DP06"
    pattern_name = "Bait and Switch"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []
        pricing = enrichment.get("pricing_breakdown", {})

        original_price  = pricing.get("baseline_price", "")
        current_price   = pricing.get("current_price", "")
        original_url    = pricing.get("baseline_url", "")
        original_product= pricing.get("baseline_product_name", "")

        for ev in evidence:
            selector = self._selector(ev)
            reason   = ev.get("reason", "")

            if "substitut" in reason.lower() and original_product:
                banner = _substitution_banner_html(original_product)
                desc   = f"Product substitution banner: was '{original_product}'"
            else:
                banner = _mismatch_banner_html(
                    original    = original_price or "lower price",
                    current     = current_price  or "higher price",
                    original_url= original_url,
                )
                desc = "Price mismatch banner above checkout price"

            patches.append(self._raw(
                css_selector = selector,
                action       = "inject_element",
                payload      = {"html": banner, "position": "before"},
                description  = desc,
            ))

        return patches
