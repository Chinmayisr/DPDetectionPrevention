"""
agents/prevention_agent/strategies/dp04_trick_question.py
DP04 — Trick Question
Strategy:
  1. UNCHECK         — enforce unchecked state on pre-checked boxes.
  2. GPT-4o rewrite  → REPLACE_TEXT for confusing double-negative labels.
  3. INJECT_ELEMENT  — tooltip ? icon beside each checkbox.
"""
from __future__ import annotations
from typing import Any
import structlog
from agents.prevention_agent.strategies.base import BaseStrategy
from agents.shared.openai_client import chat_complete_json

logger = structlog.get_logger(__name__)

_REWRITE_SYSTEM = (
    "You are a plain-language UX writer. "
    "Given a confusing or double-negative checkbox label, rewrite it in clear, "
    "direct language. Return JSON: {\"plain_label\": \"<rewritten label>\"}"
)

_TOOLTIP_HTML = (
    '<span class="dg-checkbox-tooltip" style="'
    'display:inline-block;margin-left:4px;cursor:help;'
    'background:#1565c0;color:#fff;border-radius:50%;'
    'width:16px;height:16px;font-size:11px;line-height:16px;'
    'text-align:center;font-family:sans-serif;font-weight:700;" '
    'title="{tooltip_text}">?</span>'
)


async def _plain_rewrite(original: str) -> str:
    try:
        result = await chat_complete_json(
            system_prompt = _REWRITE_SYSTEM,
            user_message  = f'Confusing label: "{original}"',
            temperature   = 0.2,
        )
        return result.get("plain_label", original).strip()
    except Exception as exc:
        logger.warning("trick_question_rewrite_failed", error=str(exc))
        return original


class TrickQuestionStrategy(BaseStrategy):
    pattern_code = "DP04"
    pattern_name = "Trick Question"

    async def build_patches(
        self,
        evidence  : list[dict[str, Any]],
        enrichment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patches: list[dict] = []

        for ev in evidence:
            selector = self._selector(ev)
            text     = self._text(ev)
            reason   = ev.get("reason", "This checkbox may be misleadingly labelled.")

            # 1 — uncheck pre-checked box and enforce via MutationObserver
            patches.append(self._raw(
                css_selector = selector,
                action       = "uncheck",
                payload      = {"enforce_on_mutation": True},
                description  = "Uncheck pre-checked trick question box",
                text_hint    = text,
            ))

            # 2 — rewrite confusing label to plain language
            plain = await _plain_rewrite(text)
            if plain and plain != text:
                patches.append(self._raw(
                    css_selector = selector,
                    action       = "replace_text",
                    payload      = {
                        "new_text"    : plain,
                        "append_note" : "(clarified by Dark Guard)",
                    },
                    description = f"Plain-language rewrite: '{text}' → '{plain}'",
                    text_hint   = text,
                ))

            # 3 — inject ? tooltip explaining what checking/unchecking actually does
            tooltip_text = (
                f"Dark Guard: {reason} "
                "Checking this box means you agree to what is described above."
            )
            patches.append(self._raw(
                css_selector = selector,
                action       = "inject_element",
                payload      = {
                    "html"    : _TOOLTIP_HTML.format(tooltip_text=tooltip_text),
                    "position": "after",
                },
                description = "Inject tooltip explaining checkbox effect",
                text_hint   = text,
            ))

        return patches