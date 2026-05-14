"""
agents/prevention_agent/strategies/dp13_forced_action.py
DP13 — Forced Action
Strategy:
  1. INJECT_ELEMENT — bypass prompt surfacing hidden guest/skip flows.
  2. INJECT_ELEMENT — notification gate override (replaces native dialog).
  3. INJECT_ELEMENT — fallback explanatory banner when no bypass is available.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy


def _bypass_prompt_html(bypass_selector: str) -> str:
    js = f"document.querySelector('{bypass_selector}')?.click();" if bypass_selector else ""
    return (
        '<div class="dg-bypass-prompt" style="'
        'background:#e8f5e9;border-left:4px solid #2e7d32;'
        'padding:10px 14px;margin:6px 0;font-family:sans-serif;font-size:13px;">'
        '✅ <strong>Dark Guard:</strong> You may be able to proceed without an account or sign-up.'
        + (
            f' <button onclick="{js}" style="'
            'margin-left:8px;background:#2e7d32;color:#fff;border:none;'
            'border-radius:3px;padding:4px 10px;cursor:pointer;font-size:12px;">'
            'Continue without signing up</button>'
            if js else ""
        )
        + '</div>'
    )


_NOTIFICATION_OVERRIDE_HTML = (
    '<div class="dg-notification-gate-override" style="'
    'background:#fce4ec;border-left:4px solid #c62828;'
    'padding:10px 14px;margin:6px 0;font-family:sans-serif;font-size:13px;">'
    '🔔 <strong>Dark Guard:</strong> This site requires notification permission to proceed. '
    'You can use this page without granting it.<br>'
    '<button onclick="history.forward();this.parentElement.remove();" style="'
    'margin-top:6px;background:#c62828;color:#fff;border:none;'
    'border-radius:3px;padding:4px 10px;cursor:pointer;">'
    'Dismiss and Continue</button>'
    '</div>'
)


_FALLBACK_BANNER_HTML = (
    '<div class="dg-forced-action-notice" style="'
    'background:#fff3e0;border-left:4px solid #e65100;'
    'padding:10px 14px;margin:6px 0;font-family:sans-serif;font-size:13px;">'
    '⚠ <strong>Dark Guard:</strong> This site requires an action before you can proceed. '
    'Dark Guard could not find an alternative path.'
    '</div>'
)


class ForcedActionStrategy(BaseStrategy):
    pattern_code = "DP13"
    pattern_name = "Forced Action"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []

        for ev in evidence:
            selector        = self._selector(ev)
            reason          = (ev.get("reason") or "").lower()
            bypass_selector = ev.get("bypass_selector", "")  # set by NLP agent if found
            gate_type       = ev.get("gate_type", "")        # "account_wall"|"notification"|"app_install"

            if gate_type == "notification" or "notif" in reason:
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "inject_element",
                    payload      = {
                        "html"    : _NOTIFICATION_OVERRIDE_HTML,
                        "position": "before",
                    },
                    description = "Notification gate override",
                ))

            elif bypass_selector:
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "inject_element",
                    payload      = {
                        "html"    : _bypass_prompt_html(bypass_selector),
                        "position": "before",
                    },
                    description = f"Bypass prompt: hidden path at '{bypass_selector}'",
                ))

            else:
                # No bypass found — explanatory fallback banner
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "inject_element",
                    payload      = {
                        "html"    : _FALLBACK_BANNER_HTML,
                        "position": "before",
                    },
                    description = "Forced action fallback notice (no bypass found)",
                ))

        return patches
