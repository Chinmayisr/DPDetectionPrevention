"""
agents/prevention_agent/strategies/dp07_basket_sneaking.py
DP07 — Basket Sneaking
Strategy:
  For each sneaked item in the cart:
  1. ADD_CLASS      — yellow highlight + warning icon on the cart row.
  2. INJECT_ELEMENT — "This item was added automatically" notice with [Remove] button.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy


def _sneak_notice_html(item_name: str, remove_selector: str = "") -> str:
    remove_js = (
        f"document.querySelector('{remove_selector}')?.click();"
        if remove_selector else ""
    )
    return (
        '<div class="dg-sneaked-notice" style="'
        'background:#fff9c4;border:1px solid #f9a825;border-radius:4px;'
        'padding:6px 10px;margin:4px 0;font-family:sans-serif;font-size:12px;">'
        f'⚠ <strong>"{item_name}"</strong> was added to your cart automatically. '
        '<button onclick="'
        + remove_js +
        'this.closest(\'.dg-sneaked-notice\').remove();" '
        'style="margin-left:8px;background:#c62828;color:#fff;border:none;'
        'border-radius:3px;padding:2px 8px;cursor:pointer;font-size:12px;">'
        'Remove</button>'
        '</div>'
    )


class BasketSneakingStrategy(BaseStrategy):
    pattern_code = "DP07"
    pattern_name = "Basket Sneaking"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []
        cart    = enrichment.get("session_cart_data", {})
        sneaked = cart.get("sneaked_items", [])

        # Use enrichment sneaked_items if available; fall back to evidence items
        items_to_flag: list[dict] = sneaked if sneaked else [
            {"item_name": ev.get("text", "Unknown item"), "css_selector": ev.get("css_selector", "")}
            for ev in evidence
        ]

        for item in items_to_flag:
            item_name      = item.get("item_name", "Unknown item")
            item_selector  = item.get("css_selector", "")
            remove_selector= item.get("remove_button_selector", "")

            if not item_selector:
                continue

            # 1 — yellow highlight row
            patches.append(self._raw(
                css_selector = item_selector,
                action       = "add_class",
                payload      = {
                    "classes"        : ["dg-sneaked-item"],
                    "style_override" : "background:#fff9c4!important;border-left:3px solid #f9a825!important;",
                },
                description = f"Highlight auto-added cart item: {item_name}",
            ))

            # 2 — inject removal notice
            patches.append(self._raw(
                css_selector = item_selector,
                action       = "inject_element",
                payload      = {
                    "html"    : _sneak_notice_html(item_name, remove_selector),
                    "position": "after",
                },
                description = f"Auto-add notice for: {item_name}",
            ))

        return patches
