"""
agents/prevention_agent/strategies/dp08_subscription_trap.py
DP08 — Subscription Trap
Strategy:
  1. INJECT_ELEMENT — subscription notice panel below CTA showing renewal terms.
  2. ADD_CLASS      — pulsing red border on the subscription price element.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy


def _subscription_notice_html(
    amount      : str,
    cycle       : str,
    cancel_url  : str,
    renewal_date: str,
) -> str:
    cancel_html = (
        f'<a href="{cancel_url}" target="_blank" style="color:#0d47a1;">'
        'Cancellation page →</a>'
        if cancel_url
        else '<span style="color:#b71c1c;">⚠ No easy cancellation option was detected.</span>'
    )
    renewal_info = f" on {renewal_date}" if renewal_date else ""
    return (
        '<div class="dg-subscription-notice" style="'
        'background:#e8f5e9;border-left:4px solid #2e7d32;'
        'padding:10px 14px;margin:6px 0;font-family:sans-serif;font-size:13px;">'
        '<strong>📋 Dark Guard Subscription Summary</strong><br>'
        f'You will be charged <strong>{amount}</strong>{renewal_info}. '
        f'Auto-renews {cycle}.<br>'
        f'{cancel_html}'
        '</div>'
    )


class SubscriptionTrapStrategy(BaseStrategy):
    pattern_code = "DP08"
    pattern_name = "Subscription Trap"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []
        bdata = enrichment.get("behavioral_data", {})
        sub   = bdata.get("subscription_flow", {})
        bill  = bdata.get("billing_data", {})

        amount       = bill.get("amount") or sub.get("price", "")
        cycle        = bill.get("billing_cycle") or sub.get("cycle", "periodically")
        cancel_url   = sub.get("cancel_url", "")
        renewal_date = bill.get("next_billing_date", "")

        for ev in evidence:
            selector = self._selector(ev)

            # 1 — inject cancellation + renewal notice below subscription CTA
            notice = _subscription_notice_html(amount, cycle, cancel_url, renewal_date)
            patches.append(self._raw(
                css_selector = selector,
                action       = "inject_element",
                payload      = {"html": notice, "position": "after"},
                description  = "Subscription renewal terms + cancellation link",
            ))

            # 2 — pulsing red border to draw attention before commitment
            patches.append(self._raw(
                css_selector = selector,
                action       = "add_class",
                payload      = {
                    "classes"        : ["dg-auto-renew-highlight"],
                    "style_override" : (
                        "border:2px solid #c62828!important;"
                        "animation:dg-pulse 0.8s 3!important;"
                    ),
                },
                description = "Pulsing red border on subscription price",
            ))

        return patches
