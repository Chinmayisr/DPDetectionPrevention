"""
agents/orchestrator_agent/nodes/synthesizer.py
─────────────────────────────────────────────────────────────────
Synthesizer node — the only node in the orchestrator that calls the LLM.

Responsibilities:
  1. Collect all pattern results from all invoked agents
  2. Deduplicate cross-agent detections (DP03 detected by NLP + Visual
     → one UnifiedPatternResult with both agents listed, higher confidence kept)
  3. Compute overall severity score using PATTERN_SEVERITY_WEIGHTS
  4. Call GPT-4o to generate a brief human-readable synthesis summary
  5. Build and return the final OrchestratorReport
"""
from __future__ import annotations

import time
from typing import Any

import structlog

from agents.orchestrator_agent.models import (
    PATTERN_SEVERITY_WEIGHTS,
    OrchestratorReport,
    UnifiedPatternResult,
    compute_severity,
)
from agents.orchestrator_agent.state import OrchestratorState
from agents.shared.models import PATTERN_NAMES, DarkPatternCode
from agents.shared.openai_client import chat_complete_json

logger = structlog.get_logger(__name__)

# Maps pattern code string → agent that owns it
# Used to assign detected_by when only one agent reports a pattern
_CODE_AGENT_MAP: dict[str, str] = {
    "DP01": "nlp", "DP02": "nlp", "DP03": "nlp", "DP04": "nlp",
    "DP05": "pricing", "DP06": "pricing",
    "DP07": "behavioral", "DP08": "behavioral", "DP09": "behavioral",
    "DP10": "behavioral", "DP11": "behavioral", "DP13": "behavioral",
    "DP12": "visual",
}

# DP03 is detected by both NLP (text) and Visual (screenshot)
_DUAL_AGENT_PATTERNS: set[str] = {"DP03"}

_SYNTHESIS_SYSTEM_PROMPT = """\
You are a dark pattern analysis assistant for Dark Guard AI.
You will receive a structured list of dark patterns detected on a webpage.

Your task:
1. Write a concise 2-3 sentence plain-English summary describing the dark patterns
   found on this page. Mention the most serious ones by name. Be direct and factual.
2. Identify the single most critical pattern code (e.g. "DP08") from the detected list.
   If nothing was detected, return null.

Respond ONLY with a JSON object in this exact format:
{
  "synthesis_summary": "<2-3 sentence summary>",
  "critical_pattern_code": "<DP code string or null>"
}
"""


def _collect_patterns_from_agent(
    agent_name: str,
    result: dict | None,
) -> list[dict[str, Any]]:
    """Extract pattern dicts from an agent result, tagging each with agent_name."""
    if not result or "error" in result:
        return []
    patterns = result.get("patterns", [])
    return [{**p, "_agent": agent_name} for p in patterns if isinstance(p, dict)]


def _deduplicate_patterns(
    all_raw: list[dict[str, Any]],
) -> list[UnifiedPatternResult]:
    """
    Merge pattern dicts from multiple agents into UnifiedPatternResult objects.

    Deduplication rule for cross-agent patterns (currently only DP03):
      - Keep the HIGHER confidence score
      - Merge evidence lists (deduplicated by text)
      - Set detected_by to all agents that flagged it
      - detected=True if ANY agent detected it

    All other patterns are owned by exactly one agent.
    """
    # Group by pattern_code
    grouped: dict[str, list[dict[str, Any]]] = {}
    for p in all_raw:
        code = str(p.get("pattern_code", ""))
        if code:
            grouped.setdefault(code, []).append(p)

    unified: list[UnifiedPatternResult] = []

    for code, instances in sorted(grouped.items()):
        name = PATTERN_NAMES.get(
            next((c for c in DarkPatternCode if c.value == code), None),
            code,
        )
        weight = PATTERN_SEVERITY_WEIGHTS.get(code, 5)

        if len(instances) == 1:
            p = instances[0]
            unified.append(UnifiedPatternResult(
                pattern_code=code,
                pattern_name=name,
                detected=bool(p.get("detected", False)),
                confidence=float(p.get("confidence", 0.0)),
                severity_weight=weight,
                evidence=p.get("evidence", []),
                detected_by=[p["_agent"]] if p.get("detected") else [],
            ))
        else:
            # Multiple agents reported this pattern — deduplicate
            detected_instances = [p for p in instances if p.get("detected")]
            any_detected = bool(detected_instances)

            # Best confidence from detected instances, or max from all
            best_confidence = max(
                (float(p.get("confidence", 0.0)) for p in instances), default=0.0
            )

            # Merge evidence: deduplicate by text field
            seen_texts: set[str] = set()
            merged_evidence: list[dict] = []
            for p in instances:
                for ev in p.get("evidence", []):
                    t = str(ev.get("text", ""))[:200]
                    if t and t not in seen_texts:
                        seen_texts.add(t)
                        merged_evidence.append(ev)

            detected_by = list({p["_agent"] for p in detected_instances})

            unified.append(UnifiedPatternResult(
                pattern_code=code,
                pattern_name=name,
                detected=any_detected,
                confidence=best_confidence,
                severity_weight=weight,
                evidence=merged_evidence,
                detected_by=detected_by,
            ))

    return unified


async def _call_synthesis_llm(
    url: str,
    page_type: str,
    detected: list[UnifiedPatternResult],
) -> tuple[str, str | None]:
    """
    Call GPT-4o to generate a synthesis summary and identify the critical pattern.

    Returns (synthesis_summary, critical_pattern_code | None).
    Falls back to a rule-based summary if the LLM call fails.
    """
    if not detected:
        return (
            f"No dark patterns were detected on this {page_type.lower()} page at {url}. "
            "The page appears to follow fair UX practices.",
            None,
        )

    # Format detected patterns for the prompt
    pattern_lines = "\n".join(
        f"- {p.pattern_code} ({p.pattern_name}): "
        f"confidence={p.confidence:.2f}, "
        f"detected_by={p.detected_by}, "
        f"severity_weight={p.severity_weight}"
        for p in detected
    )

    user_message = (
        f"URL: {url}\n"
        f"Page type: {page_type}\n"
        f"Detected dark patterns ({len(detected)}):\n{pattern_lines}"
    )

    try:
        response = await chat_complete_json(
            system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.1,
            max_tokens=400,
        )
        summary  = str(response.get("synthesis_summary", ""))
        critical = response.get("critical_pattern_code")
        if critical == "null" or critical == "":
            critical = None
        return summary, critical

    except Exception as exc:
        logger.warning("synthesizer_llm_fallback", error=str(exc))
        # Rule-based fallback — highest weight detected pattern
        worst = max(detected, key=lambda p: p.severity_weight * p.confidence)
        summary = (
            f"Dark Guard AI detected {len(detected)} dark pattern(s) on this "
            f"{page_type.lower()} page. The most critical is "
            f"{worst.pattern_name} ({worst.pattern_code}) with confidence "
            f"{worst.confidence:.0%}."
        )
        return summary, worst.pattern_code


async def synthesizer_node(state: OrchestratorState) -> dict:
    """
    Merge all agent results into a final OrchestratorReport.
    """
    start = time.perf_counter()
    scrape_id  = state["scrape_id"]
    session_id = state["session_id"]
    url        = state.get("url", "")
    page_type  = state.get("page_type", "OTHER")

    log = logger.bind(scrape_id=scrape_id)

    # ── Step 1: Collect raw patterns from all agents ───────────
    all_raw: list[dict[str, Any]] = []
    agents_invoked: list[str] = list(set(state.get("agents_invoked", [])))

    for agent_name, result_key in [
        ("nlp",        "nlp_result"),
        ("pricing",    "pricing_result"),
        ("behavioral", "behavioral_result"),
        ("visual",     "visual_result"),
    ]:
        if agent_name in agents_invoked:
            raw = _collect_patterns_from_agent(agent_name, state.get(result_key))
            all_raw.extend(raw)

    # ── Step 2: Deduplicate cross-agent patterns ───────────────
    unified_patterns = _deduplicate_patterns(all_raw)
    detected_patterns = [p for p in unified_patterns if p.detected]

    # ── Step 3: Severity score ────────────────────────────────
    severity_score, severity_label = compute_severity(detected_patterns)

    # ── Step 4: Cross-agent enrichments ───────────────────────
    financial_impact: dict[str, Any] = {}
    pricing_result = state.get("pricing_result")
    if pricing_result and "financial_impact" in pricing_result:
        financial_impact = pricing_result["financial_impact"]

    behavioral_severity_score = 0.0
    behavioral_severity_label = "none"
    behavioral_result = state.get("behavioral_result")
    if behavioral_result and "error" not in behavioral_result:
        behavioral_severity_score = float(
            behavioral_result.get("behavioral_severity_score", 0.0)
        )
        behavioral_severity_label = behavioral_result.get("severity_label", "none")

    # ── Step 5: LLM synthesis summary ─────────────────────────
    synthesis_summary, critical_pattern_code = await _call_synthesis_llm(
        url=url,
        page_type=page_type,
        detected=detected_patterns,
    )

    duration_ms = int((time.perf_counter() - start) * 1000)

    # ── Step 6: Build report ───────────────────────────────────
    report = OrchestratorReport(
        scrape_id=scrape_id,
        session_id=session_id,
        url=url,
        page_type=page_type,
        agents_invoked=agents_invoked,
        total_patterns_checked=len(unified_patterns),
        iterations_run=state.get("iteration", 1),
        all_patterns=unified_patterns,
        detected_patterns=detected_patterns,
        total_detected=len(detected_patterns),
        overall_severity_score=severity_score,
        overall_severity_label=severity_label,
        critical_pattern_code=critical_pattern_code,
        financial_impact=financial_impact,
        behavioral_severity_score=behavioral_severity_score,
        behavioral_severity_label=behavioral_severity_label,
        synthesis_summary=synthesis_summary,
        scan_duration_ms=duration_ms,
        errors=state.get("errors", []),
    )

    log.info(
        "synthesizer_complete",
        total_detected=report.total_detected,
        severity_label=report.overall_severity_label,
        severity_score=report.overall_severity_score,
        agents_invoked=agents_invoked,
        iterations=report.iterations_run,
        duration_ms=duration_ms,
    )

    return {"orchestrator_report": report}
