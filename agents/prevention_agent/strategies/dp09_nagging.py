"""
agents/prevention_agent/strategies/dp09_nagging.py
DP09 — Nagging
Strategy:
  1. ADD_CLASS      — collapse the repeated popup.
  2. INJECT_ELEMENT — "Dark Guard suppressed a repeated prompt" bar
                      with a [Show anyway] toggle.
  For push-notification nags: INJECT_ELEMENT overrides native prompt with
  a custom inline notice.
"""
from __future__ import annotations
from typing import Any
from agents.prevention_agent.strategies.base import BaseStrategy


def _suppress_bar_html(element_hash: str) -> str:
    return (
        f'<div class="dg-nagging-bar" data-hash="{element_hash}" style="'
        'background:#e3f2fd;border:1px solid #1565c0;border-radius:4px;'
        'padding:6px 10px;font-family:sans-serif;font-size:12px;margin:4px 0;">'
        '🔕 Dark Guard suppressed a repeated prompt. '
        '<button onclick="'
        "var el=this.closest('.dg-nagging-bar').nextElementSibling;"
        "if(el)el.style.display=el.style.display==='none'?'':'none';"
        '" style="margin-left:6px;background:#1565c0;color:#fff;border:none;'
        'border-radius:3px;padding:2px 8px;cursor:pointer;font-size:11px;">'
        'Show anyway</button>'
        '</div>'
    )


_NOTIFICATION_BLOCK_HTML = (
    '<div class="dg-notification-block" style="'
    'background:#fce4ec;border-left:4px solid #c62828;'
    'padding:10px 14px;margin:6px 0;font-family:sans-serif;font-size:13px;">'
    '🔔 <strong>Dark Guard:</strong> This site is requesting notification permission. '
    'You can use this page without granting it.<br>'
    '<button onclick="this.parentElement.remove();" style="'
    'margin-top:6px;background:#c62828;color:#fff;border:none;'
    'border-radius:3px;padding:4px 10px;cursor:pointer;">'
    'Dismiss and Continue</button>'
    '</div>'
)


class NaggingStrategy(BaseStrategy):
    pattern_code = "DP09"
    pattern_name = "Nagging"

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

            is_notification = "notif" in reason or "notif" in text.lower()

            if is_notification:
                # Inject custom inline block replacing the permission prompt
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "inject_element",
                    payload      = {
                        "html"    : _NOTIFICATION_BLOCK_HTML,
                        "position": "before",
                    },
                    description = "Inline notification permission override",
                ))
            else:
                # Collapse the nagging element
                element_hash = str(abs(hash(selector)))[:8]

                patches.append(self._raw(
                    css_selector = selector,
                    action       = "add_class",
                    payload      = {
                        "classes"        : ["dg-suppressed-popup"],
                        "style_override" : "display:none!important;",
                    },
                    description = "Hide repeated popup",
                ))

                # Inject suppression notice + show-anyway toggle above the element
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "inject_element",
                    payload      = {
                        "html"    : _suppress_bar_html(element_hash),
                        "position": "before",
                    },
                    description = "Suppression notice with show-anyway toggle",
                ))

        return patches
