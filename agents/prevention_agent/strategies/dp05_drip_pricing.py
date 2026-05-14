"""
agents/prevention_agent/strategies/dp05_drip_pricing.py
DP05 — Drip Pricing
Strategy:
  INJECT_ELEMENT — sticky fee-breakdown panel at page top showing all
  hidden charges and the true total computed by the Pricing Agent.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy


def _build_fee_panel_html(breakdown: dict) -> str:
    base      = breakdown.get("base_price", "N/A")
    total     = breakdown.get("total_price", "N/A")
    fees      = breakdown.get("fee_breakdown", [])
    currency  = breakdown.get("currency_symbol", "₹")

    rows = ""
    for fee in fees:
        name   = fee.get("name", "Fee")
        amount = fee.get("amount", "")
        rows += (
            f'<tr><td style="padding:2px 8px;color:#555;">{name}</td>'
            f'<td style="padding:2px 8px;text-align:right;color:#b71c1c;">+{currency}{amount}</td></tr>'
        )

    return f"""
<div id="dg-drip-panel" style="
  position:fixed;top:0;left:0;width:100%;z-index:2147483646;
  background:#fff3e0;border-bottom:3px solid #e65100;
  font-family:sans-serif;font-size:13px;padding:10px 16px;
  box-shadow:0 2px 8px rgba(0,0,0,.15);">
  <strong style="color:#bf360c;">⚠ Dark Guard: Hidden fees detected</strong>
  <span style="float:right;cursor:pointer;color:#555;" onclick="document.getElementById('dg-drip-panel').remove()">✕ Close</span>
  <table style="margin-top:6px;width:auto;">
    <tr><td style="padding:2px 8px;">Advertised price</td>
        <td style="padding:2px 8px;text-align:right;">{currency}{base}</td></tr>
    {rows}
    <tr style="border-top:1px solid #e65100;">
      <td style="padding:4px 8px;font-weight:700;">Total you will pay</td>
      <td style="padding:4px 8px;text-align:right;font-weight:700;color:#b71c1c;">{currency}{total}</td>
    </tr>
  </table>
</div>
"""


class DripPricingStrategy(BaseStrategy):
    pattern_code = "DP05"
    pattern_name = "Drip Pricing"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []

        pricing = enrichment.get("pricing_breakdown", {})
        if not pricing:
            # Fallback: if no enrichment, badge the first evidence element
            for ev in evidence:
                patches.append(self._raw(
                    css_selector = self._selector(ev),
                    action       = "add_badge",
                    payload      = {
                        "label"   : "⚠ Hidden fees",
                        "color"   : "#fff",
                        "bg_color": "#e65100",
                        "title"   : "Dark Guard: Additional fees may be added at checkout.",
                    },
                    description = "Drip pricing badge (no breakdown available)",
                ))
            return patches

        # Inject the full fee breakdown panel at body level (page top)
        panel_html = _build_fee_panel_html(pricing)
        patches.append(self._raw(
            css_selector = "body",
            action       = "inject_element",
            payload      = {
                "html"    : panel_html,
                "position": "prepend",
            },
            description = "Sticky fee-breakdown panel showing true total",
        ))

        return patches
