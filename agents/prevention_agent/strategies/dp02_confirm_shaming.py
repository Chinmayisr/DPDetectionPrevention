"""
agents/prevention_agent/strategies/dp02_confirm_shaming.py
─────────────────────────────────────────────────────────────
DP02 — Confirm Shaming

Strategy:
  1. GPT-4o rewrites the shaming opt-out text to a neutral equivalent.
  2. REPLACE_TEXT   — swap in the neutral text.
  3. ADD_CLASS      — yellow border on the rewritten button.
"""
from __future__ import annotations
import json
from typing import Any

import structlog

from agents.prevention_agent.strategies.base import BaseStrategy
from agents.shared.openai_client import chat_complete_json

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a UX ethics assistant. Given a shaming opt-out button label, "
    "rewrite it as a neutral 3-6 word alternative that preserves the action "
    "(decline / skip / no thanks) without any emotional manipulation or self-deprecation. "
    "Return JSON: {\"neutral_text\": \"<rewritten label>\"}"
)


async def _neutral_rewrite(original_text: str) -> str:
    """Call GPT-4o to produce a neutral opt-out label. Falls back to generic."""
    try:
        result = await chat_complete_json(
            system_prompt = _SYSTEM_PROMPT,
            user_message  = f'Shaming label: "{original_text}"',
            temperature   = 0.2,
        )
        return result.get("neutral_text", "No thanks, skip").strip()
    except Exception as exc:
        logger.warning("confirm_shaming_rewrite_failed", error=str(exc))
        return "No thanks, skip"


class ConfirmShamingStrategy(BaseStrategy):
    pattern_code = "DP02"
    pattern_name = "Confirm Shaming"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []

        for ev in evidence:
            selector     = self._selector(ev)
            original_text = self._text(ev)

            # GPT-4o neutral rewrite
            neutral_text = await _neutral_rewrite(original_text)

            # 1 — replace shaming text with neutral version
            patches.append(self._raw(
                css_selector = selector,
                action       = "replace_text",
                payload      = {
                    "new_text"     : neutral_text,
                    "append_note"  : "(reworded by Dark Guard)",
                },
                description = f"Neutral rewrite: '{original_text}' → '{neutral_text}'",
                text_hint   = original_text,
            ))

            # 2 — highlight the button so the user notices it was modified
            patches.append(self._raw(
                css_selector = selector,
                action       = "add_class",
                payload      = {
                    "classes"        : ["dg-neutral-btn"],
                    "style_override" : "border:2px solid #f9a825!important;",
                },
                description = "Yellow border on rewritten opt-out button",
                text_hint   = original_text,
            ))

        return patches