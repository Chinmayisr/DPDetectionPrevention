"""
agents/shared/models.py
Canonical detection result schemas shared across all agents.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DarkPatternCode(str, Enum):
    FALSE_URGENCY   = "DP01"
    CONFIRM_SHAMING = "DP02"
    DISGUISED_ADS   = "DP03"
    TRICK_QUESTION  = "DP04"


PATTERN_NAMES: dict[DarkPatternCode, str] = {
    DarkPatternCode.FALSE_URGENCY:   "False Urgency",
    DarkPatternCode.CONFIRM_SHAMING: "Confirm Shaming",
    DarkPatternCode.DISGUISED_ADS:   "Disguised Ads",
    DarkPatternCode.TRICK_QUESTION:  "Trick Question",
}


class EvidenceItem(BaseModel):
    text: str
    location: str | None = None
    reason: str | None = None
    css_selector: str | None = None


class SinglePatternResult(BaseModel):
    pattern_code: DarkPatternCode
    pattern_name: str
    detected: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = []
    raw_llm_response: str | None = None
    error: str | None = None


class AggregatedDetectionResult(BaseModel):
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
        return [p for p in self.patterns if p.detected]