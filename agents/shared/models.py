"""
agents/shared/models.py
─────────────────────────────────────────────────────────────────
Canonical detection result schemas shared across all agents.
Covers all 11 dark pattern codes (DP01–DP11).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Dark Pattern Catalogue ────────────────────────────────────

class DarkPatternCode(str, Enum):
    # NLP Agent
    FALSE_URGENCY   = "DP01"
    CONFIRM_SHAMING = "DP02"
    DISGUISED_ADS   = "DP03"
    TRICK_QUESTION  = "DP04"
    # Pricing Agent
    DRIP_PRICING    = "DP05"
    BAIT_SWITCH     = "DP06"
    # Behavioral Agent
    BASKET_SNEAKING   = "DP07"
    SUBSCRIPTION_TRAP = "DP08"
    NAGGING           = "DP09"
    SAAS_BILLING      = "DP10"
    ROGUE_MALICIOUS   = "DP11"
    FORCED_ACTION       = "DP13"
    #visual agent
    INTERFACE_INTERFERENCE = "DP12"

PATTERN_NAMES: dict[DarkPatternCode, str] = {
    DarkPatternCode.FALSE_URGENCY:    "False Urgency",
    DarkPatternCode.CONFIRM_SHAMING:  "Confirm Shaming",
    DarkPatternCode.DISGUISED_ADS:    "Disguised Ads",
    DarkPatternCode.TRICK_QUESTION:   "Trick Question",
    DarkPatternCode.DRIP_PRICING:     "Drip Pricing",
    DarkPatternCode.BAIT_SWITCH:      "Bait and Switch",
    DarkPatternCode.BASKET_SNEAKING:  "Basket Sneaking",
    DarkPatternCode.SUBSCRIPTION_TRAP:"Subscription Trap",
    DarkPatternCode.NAGGING:          "Nagging",
    DarkPatternCode.SAAS_BILLING:     "SaaS Billing",
    DarkPatternCode.ROGUE_MALICIOUS:  "Rogue and Malicious Content",
    DarkPatternCode.INTERFACE_INTERFERENCE: "Interface Interference",
    DarkPatternCode.FORCED_ACTION: "Forced Action",
}

PATTERN_AGENT_MAP: dict[DarkPatternCode, str] = {
    DarkPatternCode.FALSE_URGENCY:    "nlp",
    DarkPatternCode.CONFIRM_SHAMING:  "nlp",
    DarkPatternCode.DISGUISED_ADS:    "nlp",
    DarkPatternCode.TRICK_QUESTION:   "nlp",
    DarkPatternCode.DRIP_PRICING:     "pricing",
    DarkPatternCode.BAIT_SWITCH:      "pricing",
    DarkPatternCode.BASKET_SNEAKING:  "behavioral",
    DarkPatternCode.SUBSCRIPTION_TRAP:"behavioral",
    DarkPatternCode.NAGGING:          "behavioral",
    DarkPatternCode.SAAS_BILLING:     "behavioral",
    DarkPatternCode.ROGUE_MALICIOUS:  "behavioral",
}


# ── Evidence ──────────────────────────────────────────────────

class EvidenceItem(BaseModel):
    """A single piece of text/element evidence for a detection."""
    text: str
    location: str | None = None
    reason: str | None = None
    css_selector: str | None = None


# ── Single Pattern Result ─────────────────────────────────────

class SinglePatternResult(BaseModel):
    """
    Output of one detection node.
    pattern_code accepts both DarkPatternCode enum and plain string
    so pricing/behavioral agents can use "DP05"/"DP07" etc. directly.
    """
    pattern_code: DarkPatternCode | str
    pattern_name: str
    detected: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = []
    raw_llm_response: str | None = None
    error: str | None = None

    def code_str(self) -> str:
        """Always return the string value of the pattern code."""
        if isinstance(self.pattern_code, DarkPatternCode):
            return self.pattern_code.value
        return str(self.pattern_code)


# ── NLP Aggregated Result ─────────────────────────────────────

class AggregatedDetectionResult(BaseModel):
    """
    Final output of the NLP Agent.
    Returned by run_nlp_agent() and stored at dg:detection:{scrape_id}.
    """
    scrape_id: str
    session_id: str
    url: str
    page_type: str
    patterns: list[SinglePatternResult]
    total_detected: int = 0
    detection_duration_ms: int = 0
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def detected_patterns(self) -> list[SinglePatternResult]:
        """Return only patterns where detected=True."""
        return [p for p in self.patterns if p.detected]


# ── Unified Scan Result ───────────────────────────────────────

class UnifiedScanResult(BaseModel):
    """
    Combined result from all three agents (NLP + Pricing + Behavioral).
    Used by the Orchestrator to assemble the final response sent to
    the browser extension.
    """
    scrape_id: str
    session_id: str
    url: str
    page_type: str

    # Per-agent results
    nlp_patterns:        list[SinglePatternResult] = []
    pricing_patterns:    list[SinglePatternResult] = []
    behavioral_patterns: list[SinglePatternResult] = []

    # Aggregated stats
    total_detected: int = 0
    nlp_detected: int = 0
    pricing_detected: int = 0
    behavioral_detected: int = 0

    # Financial impact (from pricing agent)
    financial_impact: dict[str, Any] = {}

    # Behavioral severity (from behavioral agent)
    behavioral_severity_score: float = 0.0
    behavioral_severity_label: str = "none"

    # Timing
    total_duration_ms: int = 0
    scanned_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def all_detected_patterns(self) -> list[SinglePatternResult]:
        """Return all detected patterns across all agents."""
        all_p = self.nlp_patterns + self.pricing_patterns + self.behavioral_patterns
        return [p for p in all_p if p.detected]


# ── MCP Tool Input / Output Schemas ──────────────────────────

class StoreScanInput(BaseModel):
    scrape_id: str
    session_id: str
    detection_result: dict[str, Any]
    prevention_result: dict[str, Any]


class FetchSimilarInput(BaseModel):
    text: str
    top_k: int = 5
    pattern_code: DarkPatternCode | None = None


class FetchSimilarOutput(BaseModel):
    matches: list[dict[str, Any]]