"""
agents/prevention_agent/nodes/conflict_resolver.py
─────────────────────────────────────────────────────────────────
Conflict resolver node — merges patch instructions that target the
same CSS selector to avoid redundant or contradictory mutations.

Rules
─────
1. ADD_CLASS targeting the same selector: merge all classes into
   one instruction, concatenate style_override strings.

2. INJECT_ELEMENT on the same selector with the same position:
   allowed — multiple injections are additive. No merge needed.

3. REPLACE_TEXT + REPLACE_TEXT on the same selector: keep only
   the higher-priority pattern's instruction (lower priority number).

4. INTERCEPT_CLICK + anything on the same selector: intercept_click
   wins and other click-related patches are dropped (safety-critical).

5. After merging, sort by priority (ascending) so content script
   applies safety-critical patches first.
"""
from __future__ import annotations
from collections import defaultdict
import structlog
from agents.prevention_agent.state import PreventionAgentState
from agents.prevention_agent.patch_builder import build_patches_from_dicts

logger = structlog.get_logger(__name__)


def _resolve(raw_patches: list[dict]) -> list[dict]:
    # Group by (selector, action)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for p in raw_patches:
        key = (p["css_selector"], p["action"])
        groups[key].append(p)

    resolved: list[dict] = []

    for (selector, action), patches in groups.items():

        if action == "add_class":
            # Merge all classes + style_overrides into one instruction
            merged_classes: list[str] = []
            merged_style   = ""
            base = patches[0].copy()
            for p in patches:
                merged_classes.extend(p["payload"].get("classes", []))
                merged_style += p["payload"].get("style_override", "")
            base["payload"] = {
                "classes"        : list(dict.fromkeys(merged_classes)),  # deduplicate
                "style_override" : merged_style,
            }
            resolved.append(base)

        elif action == "replace_text" and len(patches) > 1:
            # Keep highest-priority (lowest priority number) replace_text
            best = min(patches, key=lambda p: p.get("priority", 5))
            resolved.append(best)

        elif action == "intercept_click":
            # intercept_click wins — drop other non-inject patches for this selector
            resolved.append(patches[0])
            # Remove any replace_text or add_class for the same selector from resolved
            resolved = [
                r for r in resolved
                if not (
                    r["css_selector"] == selector
                    and r["action"] in ("replace_text", "add_class")
                )
            ]

        else:
            # All other actions (inject_element, add_badge, uncheck) are additive
            resolved.extend(patches)

    return resolved


async def conflict_resolver_node(state: PreventionAgentState) -> dict:
    raw  = state.get("raw_patch_instructions", [])
    log  = logger.bind(scrape_id=state["scrape_id"])

    resolved_dicts = _resolve(raw)

    # Validate through Pydantic before handing to aggregate
    validated = build_patches_from_dicts(resolved_dicts)

    # Sort by priority (safety-critical first)
    validated.sort(key=lambda p: p.priority)

    log.info(
        "conflict_resolution_done",
        raw_count     =len(raw),
        resolved_count=len(validated),
        dropped       =len(raw) - len(resolved_dicts),
    )

    return {
        "resolved_patch_instructions": [p.model_dump() for p in validated]
    }
