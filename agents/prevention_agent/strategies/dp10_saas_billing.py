"""
agents/prevention_agent/strategies/dp10_saas_billing.py
DP10 — SaaS Billing
Strategy:
  1. INJECT_ELEMENT — clarification tooltip showing computed true cost
                      (per-seat, annual total, upgrade diff).
  2. ADD_CLASS      — orange underline on elements with billing discrepancies.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy


def _billing_tooltip_html(clarification: str) -> str:
    return (
        '<div class="dg-billing-tooltip" style="'
        'background:#fff8e1;border:1px solid #f9a825;border-radius:4px;'
        'padding:8px 12px;margin:4px 0;font-family:sans-serif;font-size:13px;">'
        f'💰 <strong>Dark Guard Billing Clarification:</strong> {clarification}'
        '</div>'
    )


class SaasBillingStrategy(BaseStrategy):
    pattern_code = "DP10"
    pattern_name = "SaaS Billing"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []
        bill = enrichment.get("behavioral_data", {}).get("billing_data", {})

        per_seat    = bill.get("per_seat_price", "")
        seat_count  = bill.get("seat_count", "")
        total       = bill.get("total_annual", "")
        cycle       = bill.get("billing_cycle", "monthly")
        currency    = bill.get("currency_symbol", "$")

        for ev in evidence:
            selector = self._selector(ev)
            reason   = ev.get("reason", "")

            # Build a human-readable clarification from available billing data
            if per_seat and seat_count:
                clarification = (
                    f"Per seat: {currency}{per_seat}/{cycle}. "
                    f"For {seat_count} seats: {currency}{total} billed annually."
                )
            elif total:
                clarification = (
                    f"True total cost: {currency}{total} ({cycle}). "
                    f"Details: {reason}"
                )
            else:
                clarification = reason or "Billing terms may be unclear. Review carefully."

            # 1 — inject tooltip beside the price/plan element
            patches.append(self._raw(
                css_selector = selector,
                action       = "inject_element",
                payload      = {
                    "html"    : _billing_tooltip_html(clarification),
                    "position": "after",
                },
                description = "SaaS billing clarification tooltip",
            ))

            # 2 — orange underline on the discrepant element
            patches.append(self._raw(
                css_selector = selector,
                action       = "add_class",
                payload      = {
                    "classes"        : ["dg-billing-highlight"],
                    "style_override" : "text-decoration:underline wavy #f9a825!important;",
                },
                description = "Orange wavy underline on billing anomaly",
            ))

        return patches
