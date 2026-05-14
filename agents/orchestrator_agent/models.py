"""
agents/orchestrator_agent/models.py
─────────────────────────────────────────────────────────────────
Output schemas for the Orchestrator Agent.

OrchestratorReport is the final unified payload returned to the
scan endpoint and ultimately to the browser extension.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# ── Per-pattern severity weights ──────────────────────────────
# Used by the synthesizer to compute the overall page score.
# Higher = more harmful to the user.
PATTERN_SEVERITY_WEIGHTS: dict[str, int] = {
    "DP01": 5,   # False Urgency          — moderate manipulation
    "DP02": 6,   # Confirm Shaming        — psychological pressure
    "DP03": 4,   # Disguised Ads          — misleading but lower harm
    "DP04": 5,   # Trick Question         — moderate deception
    "DP05": 7,   # Drip Pricing           — direct financial harm
    "DP06": 8,   # Bait and Switch        — direct financial harm, high severity
    "DP07": 8,   # Basket Sneaking        — direct financial harm
    "DP08": 9,   # Subscription Trap      — ongoing financial harm
    "DP09": 4,   # Nagging                — annoying but lower harm
    "DP10": 6,   # SaaS Billing           — opaque billing
    "DP11": 9,   # Rogue and Malicious    — highest harm — potential fraud
    "DP12": 5,   # Interface Interference — visual manipulation
    "DP13": 8,   # Forced Action          — coerced consent
}

# Maximum possible weighted sum (all patterns detected at confidence=1.0)
_MAX_WEIGHT_SUM: float = float(sum(PATTERN_SEVERITY_WEIGHTS.values()))


# ── Routing table — page type → agents to invoke ─────────────
PAGE_TYPE_AGENT_MAP: dict[str, list[str]] = {
    # Product pages: check text, visuals, and historical price comparison
    "PRODUCT":        ["nlp", "visual", "pricing"],
    # Cart/checkout/payment: all agents — highest risk of financial dark patterns
    "CART":           ["nlp", "pricing", "behavioral", "visual"],
    "CHECKOUT":       ["nlp", "pricing", "behavioral", "visual"],
    "PAYMENT":        ["nlp", "pricing", "behavioral", "visual"],
    # Listing pages: text and visual only — no pricing context yet
    "SEARCH_RESULTS": ["nlp", "visual"],
    "CATEGORY":       ["nlp", "visual"],
    # Home page: text and visual dark patterns common
    "HOME":           ["nlp", "visual"],
    # Login gates: forced action and confirm shaming common
    "LOGIN_GATE":     ["nlp", "behavioral"],
    # Order confirmation: nagging, subscription traps common
    "ORDER_CONFIRM":  ["nlp", "behavioral"],
    # Unknown page type: safe defaults
    "OTHER":          ["nlp", "visual"],
}

# Confidence bands
LOW_CONFIDENCE_THRESHOLD: float = 0.55   # below this → skip re-run
RERUN_CONFIDENCE_BAND: float = 0.70      # between LOW and this → re-run
MAX_ITERATIONS: int = 2                  # max times dispatcher can be called


# ── Unified pattern result ────────────────────────────────────

class UnifiedPatternResult(BaseModel):
    """
    A single dark pattern result after cross-agent deduplication.

    When NLP and Visual both detect DP03, they are merged into one
    UnifiedPatternResult with detected_by = ["nlp", "visual"] and
    the highest confidence score retained.
    """
    pattern_code:    str
    pattern_name:    str
    detected:        bool
    confidence:      float
    severity_weight: int = 5
    evidence:        list[dict[str, Any]] = []
    detected_by:     list[str] = []        # agent names that flagged this


# ── Orchestrator report ───────────────────────────────────────

class OrchestratorReport(BaseModel):
    """
    Final unified output of the Orchestrator Agent.
    Returned by run_orchestrator() and consumed by the scan endpoint.
    """
    # Identity
    scrape_id:  str
    session_id: str
    url:        str
    page_type:  str

    # Agent execution metadata
    agents_invoked:         list[str]   # which agents were actually called
    total_patterns_checked: int         # total patterns evaluated (across all agents)
    iterations_run:         int         # 1 = normal, 2 = had low-confidence re-run

    # Detection results
    all_patterns:      list[UnifiedPatternResult]   # every pattern (detected or not)
    detected_patterns: list[UnifiedPatternResult]   # only detected=True
    total_detected:    int

    # Severity
    overall_severity_score: float   # 0.0 – 10.0
    overall_severity_label: str     # none / low / medium / high / critical
    critical_pattern_code:  str | None = None  # the single most critical detected pattern

    # Cross-agent enrichments
    financial_impact:           dict[str, Any] = {}
    behavioral_severity_score:  float = 0.0
    behavioral_severity_label:  str   = "none"

    # LLM-generated narrative (from synthesizer node)
    synthesis_summary: str = ""

    # Timing
    scan_duration_ms: int = 0
    scanned_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Error log — non-fatal agent errors are captured here
    errors: list[str] = []


def compute_severity(detected: list[UnifiedPatternResult]) -> tuple[float, str]:
    """
    Compute overall severity score (0–10) and label from detected patterns.

    Uses weighted sum: each pattern contributes its severity_weight * confidence.
    Normalises against the maximum possible weighted sum across all 13 patterns.
    """
    if not detected:
        return 0.0, "none"

    weighted_sum = sum(
        p.severity_weight * p.confidence
        for p in detected
    )
    score = min(10.0, round((weighted_sum / _MAX_WEIGHT_SUM) * 10, 2))

    label = (
        "critical" if score >= 7.0 else
        "high"     if score >= 5.0 else
        "medium"   if score >= 3.0 else
        "low"      if score >  0.0 else
        "none"
    )
    return score, label
