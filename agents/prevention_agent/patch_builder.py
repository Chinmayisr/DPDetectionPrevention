"""
agents/prevention_agent/patch_builder.py
Validates and assembles PatchInstruction objects.
Safety rules: REPLACE_TEXT blocked on body/html/head, payload schema enforced.
"""
from __future__ import annotations
import structlog
from agents.prevention_agent.models import PatchAction, PatchInstruction, PRIORITY

logger = structlog.get_logger(__name__)

_BLOCKED_BROAD_SELECTORS = {"body", "html", "head", "main", "#root", "#app"}

_REQUIRED_KEYS: dict[str, list[str]] = {
    "replace_text"    : ["new_text"],
    "inject_element"  : ["html", "position"],
    "add_class"       : ["classes"],
    "add_badge"       : ["label"],
    "intercept_click" : ["warning_message"],
    "uncheck"         : ["enforce_on_mutation"],
}


def build_patch(
    css_selector: str,
    action      : str | PatchAction,
    payload     : dict,
    pattern_code: str,
    pattern_name: str,
    description : str = "",
) -> PatchInstruction | None:
    selector_clean = css_selector.strip().lower()
    action_str     = action.value if isinstance(action, PatchAction) else action

    if action_str == "replace_text" and selector_clean in _BLOCKED_BROAD_SELECTORS:
        logger.warning("patch_blocked_broad_selector", selector=css_selector, pattern=pattern_code)
        return None

    for key in _REQUIRED_KEYS.get(action_str, []):
        if key not in payload:
            logger.warning("patch_missing_payload_key", key=key, action=action_str, pattern=pattern_code)
            return None

    if action_str == "add_class":
        if not isinstance(payload.get("classes"), list) or not payload["classes"]:
            logger.warning("patch_empty_classes", pattern=pattern_code)
            return None

    return PatchInstruction(
        css_selector = css_selector,
        action       = PatchAction(action_str),
        payload      = payload,
        pattern_code = pattern_code,
        pattern_name = pattern_name,
        description  = description,
        priority     = PRIORITY.get(pattern_code, 5),
    )


def build_patches_from_dicts(raw_list: list[dict]) -> list[PatchInstruction]:
    results: list[PatchInstruction] = []
    for raw in raw_list:
        patch = build_patch(
            css_selector = raw.get("css_selector", ""),
            action       = raw.get("action", ""),
            payload      = raw.get("payload", {}),
            pattern_code = raw.get("pattern_code", ""),
            pattern_name = raw.get("pattern_name", ""),
            description  = raw.get("description", ""),
        )
        if patch:
            results.append(patch)
    return results
