"""
backend/api/v1/scan.py
─────────────────────────────────────────────────────────────────
POST /api/v1/scan — unified dark pattern scan endpoint.

Flow:
    POST /api/v1/scan
        │
        ├─ 1. Validate ScanRequest (url + optional session_id)
        ├─ 2. Scrape page with Playwright  →  ScrapedPage
        ├─ 3. Persist all agent payloads to Redis  (SessionStore.save_scrape)
        ├─ 4. Run NLP + Pricing + Behavioral + Visual agents concurrently
        ├─ 5. Run Prevention Agent on merged detection results
        ├─ 6. Merge everything into ScanResponse
        └─ 7. Return unified JSON to the browser extension

Each agent failure is isolated — a single agent crashing does NOT abort
the entire scan. The response includes per-agent `error` fields so the
browser extension can surface partial results gracefully.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

from agents.behavioral_agent.runner  import run_behavioral_agent
from agents.nlp_agent.runner         import run_nlp_agent
from agents.pricing_agent.runner     import run_pricing_agent
from agents.visual_agent.runner      import run_visual_agent
from agents.prevention_agent.runner  import run_prevention_agent
from agents.shared.models            import AggregatedDetectionResult, SinglePatternResult
from backend.cache.redis_client      import get_redis_client
from backend.cache.session_store     import SessionStore
from backend.scraper.playwright_scraper import scrape

logger = structlog.get_logger(__name__)

router = APIRouter()


# ═════════════════════════════════════════════════════════════
#  REQUEST / RESPONSE MODELS
# ═════════════════════════════════════════════════════════════

class ScanRequest(BaseModel):
    """
    Payload sent by the browser extension to trigger a full scan.

    session_id ties multiple page scrapes together so cross-page
    detectors (Pricing, Behavioral) can compare the current page
    against previous pages in the same browsing session.

    If the extension does not yet have a session_id, omit it —
    a fresh UUID is generated and returned so the extension can
    store it for subsequent requests.
    """
    url       : HttpUrl
    session_id: str | None = Field(
        default=None,
        description="Browsing-session ID. Auto-generated if omitted.",
    )


class AgentResult(BaseModel):
    """Normalised result from a single detection agent."""
    agent         : str                       # "nlp"|"pricing"|"behavioral"|"visual"
    patterns      : list[dict[str, Any]] = []
    total_detected: int = 0
    duration_ms   : int = 0
    error         : str | None = None


class ScanResponse(BaseModel):
    """
    Unified response returned by POST /api/v1/scan.

    The browser extension uses:
      - all_detected_patterns   → badge count + popover list
      - prevention.patch_instructions → DOM mutations to apply
    """
    # ── Identity ──────────────────────────────────────────────
    scrape_id : str
    session_id: str
    url        : str
    page_type  : str

    # ── Per-agent detection results ───────────────────────────
    nlp       : AgentResult
    pricing   : AgentResult
    behavioral: AgentResult
    visual    : AgentResult

    # ── Aggregated detection stats ────────────────────────────
    total_detected       : int
    all_detected_patterns: list[dict[str, Any]]

    # ── Cross-agent enrichments ───────────────────────────────
    financial_impact          : dict[str, Any] = {}
    behavioral_severity_score : float = 0.0
    behavioral_severity_label : str   = "none"

    # ── Prevention output ─────────────────────────────────────
    # Contains patch_instructions for the browser extension content script.
    prevention: dict[str, Any] = {}

    # ── Timing ────────────────────────────────────────────────
    scrape_duration_ms    : int
    agents_duration_ms    : int
    prevention_duration_ms: int
    total_duration_ms     : int

    scanned_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ═════════════════════════════════════════════════════════════
#  AGENT RUNNER HELPERS
# Each helper isolates exceptions so one failure never stops the rest.
# ═════════════════════════════════════════════════════════════

async def _run_nlp(scrape_id: str, session_id: str) -> AgentResult:
    start = time.perf_counter()
    try:
        result: dict = await run_nlp_agent(
            scrape_id  = scrape_id,
            session_id = session_id,
        )
        # NLP agent may return a Pydantic model or a dict depending on version
        if isinstance(result, AggregatedDetectionResult):
            patterns = [_serialise_single_pattern(p) for p in result.patterns]
            detected = result.total_detected
        else:
            patterns = result.get("patterns", [])
            detected = result.get("total_detected", sum(
                1 for p in patterns if p.get("detected")
            ))
        return AgentResult(
            agent          = "nlp",
            patterns       = patterns,
            total_detected = detected,
            duration_ms    = int((time.perf_counter() - start) * 1000),
        )
    except Exception as exc:
        logger.error("nlp_agent_error", error=str(exc), scrape_id=scrape_id)
        return AgentResult(
            agent       = "nlp",
            duration_ms = int((time.perf_counter() - start) * 1000),
            error       = str(exc),
        )


async def _run_pricing(scrape_id: str, session_id: str) -> AgentResult:
    start = time.perf_counter()
    try:
        result: dict = await run_pricing_agent(
            scrape_id  = scrape_id,
            session_id = session_id,
        )
        raw_patterns: list[dict] = result.get("patterns", [])
        detected = [p for p in raw_patterns if p.get("detected", False)]
        ar = AgentResult(
            agent          = "pricing",
            patterns       = raw_patterns,
            total_detected = result.get("total_detected", len(detected)),
            duration_ms    = int((time.perf_counter() - start) * 1000),
        )
        # Stash financial_impact for the response enrichment block
        object.__setattr__(ar, "_financial_impact", result.get("financial_impact", {}))
        return ar
    except Exception as exc:
        logger.error("pricing_agent_error", error=str(exc), scrape_id=scrape_id)
        return AgentResult(
            agent       = "pricing",
            duration_ms = int((time.perf_counter() - start) * 1000),
            error       = str(exc),
        )


async def _run_behavioral(scrape_id: str, session_id: str) -> AgentResult:
    start = time.perf_counter()
    try:
        result: dict = await run_behavioral_agent(
            scrape_id  = scrape_id,
            session_id = session_id,
        )
        raw_patterns: list[dict] = result.get("patterns", [])
        detected = [p for p in raw_patterns if p.get("detected", False)]
        ar = AgentResult(
            agent          = "behavioral",
            patterns       = raw_patterns,
            total_detected = result.get("total_detected", len(detected)),
            duration_ms    = int((time.perf_counter() - start) * 1000),
        )
        # Stash severity for the response enrichment block
        object.__setattr__(ar, "_severity_score", result.get("behavioral_severity_score", 0.0))
        object.__setattr__(ar, "_severity_label", result.get("severity_label", "none"))
        return ar
    except Exception as exc:
        logger.error("behavioral_agent_error", error=str(exc), scrape_id=scrape_id)
        return AgentResult(
            agent       = "behavioral",
            duration_ms = int((time.perf_counter() - start) * 1000),
            error       = str(exc),
        )


async def _run_visual(scrape_id: str, session_id: str) -> AgentResult:
    start = time.perf_counter()
    try:
        result: dict = await run_visual_agent(
            scrape_id  = scrape_id,
            session_id = session_id,
        )
        raw_patterns: list[dict] = result.get("patterns", [])
        detected = [p for p in raw_patterns if p.get("detected", False)]
        return AgentResult(
            agent          = "visual",
            patterns       = raw_patterns,
            total_detected = result.get("total_detected", len(detected)),
            duration_ms    = int((time.perf_counter() - start) * 1000),
        )
    except Exception as exc:
        logger.error("visual_agent_error", error=str(exc), scrape_id=scrape_id)
        return AgentResult(
            agent       = "visual",
            duration_ms = int((time.perf_counter() - start) * 1000),
            error       = str(exc),
        )


# ═════════════════════════════════════════════════════════════
#  MERGE HELPERS
# ═════════════════════════════════════════════════════════════

def _collect_detected(*agent_results: AgentResult) -> list[dict[str, Any]]:
    """
    Flatten all agent results into a single list of detected-only patterns.
    Stamps each with detected_by so the extension can colour-code by agent.
    """
    detected: list[dict[str, Any]] = []
    for ar in agent_results:
        for pattern in ar.patterns:
            if pattern.get("detected", False):
                detected.append({**pattern, "detected_by": ar.agent})
    return detected


def _serialise_single_pattern(p: SinglePatternResult) -> dict[str, Any]:
    """Convert NLP agent's Pydantic SinglePatternResult into a plain dict."""
    return {
        "pattern_code": p.code_str() if hasattr(p, "code_str") else str(p.pattern_code),
        "pattern_name": p.pattern_name,
        "detected"    : p.detected,
        "confidence"  : p.confidence,
        "evidence"    : [e.model_dump() for e in p.evidence],
        "error"       : p.error,
    }


# ═════════════════════════════════════════════════════════════
#  ENDPOINT
# ═════════════════════════════════════════════════════════════

@router.post(
    "/scan",
    response_model = ScanResponse,
    status_code    = status.HTTP_200_OK,
    summary        = "Scan a URL for dark patterns",
    description    = (
        "Scrapes the given URL with Playwright, runs all four detection agents "
        "(NLP, Pricing, Behavioral, Visual) concurrently, then runs the Prevention "
        "Agent to produce DOM patch instructions. Returns a unified report."
    ),
)
async def scan_endpoint(request: ScanRequest) -> ScanResponse:
    wall_start = time.perf_counter()

    # ── Resolve session_id ────────────────────────────────────
    session_id: str = request.session_id or str(uuid.uuid4())
    url_str   : str = str(request.url)

    log = logger.bind(url=url_str, session_id=session_id)
    log.info("scan_request_received")

    # ── Step 1: Scrape ────────────────────────────────────────
    scrape_start = time.perf_counter()
    try:
        scraped_page = await scrape(url=url_str, session_id=session_id)
    except Exception as exc:
        log.error("scrape_failed", error=str(exc))
        raise HTTPException(
            status_code = status.HTTP_502_BAD_GATEWAY,
            detail      = f"Failed to scrape URL: {exc}",
        ) from exc

    scrape_duration_ms = int((time.perf_counter() - scrape_start) * 1000)
    scrape_id  = scraped_page.scrape_id
    page_type  = scraped_page.page_type.value

    log.info(
        "scrape_complete",
        scrape_id  = scrape_id,
        page_type  = page_type,
        duration_ms= scrape_duration_ms,
    )

    # ── Step 2: Persist all agent payloads to Redis ───────────
    # All four agent runners read their inputs from Redis by scrape_id.
    # This MUST complete before any agent runs.
    try:
        redis = await get_redis_client()
        store = SessionStore(redis)
        await store.save_scrape(scraped_page)
    except Exception as exc:
        log.error("session_store_failed", error=str(exc))
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = f"Failed to persist scrape to Redis: {exc}",
        ) from exc

    # ── Step 3: Run all four detection agents concurrently ────
    agents_start = time.perf_counter()
    nlp_result, pricing_result, behavioral_result, visual_result = await asyncio.gather(
        _run_nlp       (scrape_id, session_id),
        _run_pricing   (scrape_id, session_id),
        _run_behavioral(scrape_id, session_id),
        _run_visual    (scrape_id, session_id),
    )
    agents_duration_ms = int((time.perf_counter() - agents_start) * 1000)

    log.info(
        "agents_complete",
        nlp_detected       = nlp_result.total_detected,
        pricing_detected   = pricing_result.total_detected,
        behavioral_detected= behavioral_result.total_detected,
        visual_detected    = visual_result.total_detected,
        duration_ms        = agents_duration_ms,
    )

    # ── Step 4: Run Prevention Agent ──────────────────────────
    # Prevention reads all four agent results directly from Redis,
    # so it runs after the detection agents complete.
    prevention_start = time.perf_counter()
    prevention_result: dict[str, Any] = {}
    try:
        prevention_result = await run_prevention_agent(
            scrape_id  = scrape_id,
            session_id = session_id,
        )
        log.info(
            "prevention_complete",
            total_patches      = prevention_result.get("total_patches", 0),
            patterns_addressed = prevention_result.get("patterns_addressed", []),
        )
    except Exception as exc:
        log.error("prevention_agent_failed", error=str(exc))
        prevention_result = {
            "scrape_id"         : scrape_id,
            "session_id"        : session_id,
            "patch_instructions": [],
            "patterns_addressed": [],
            "total_patches"     : 0,
            "error"             : str(exc),
        }
    prevention_duration_ms = int((time.perf_counter() - prevention_start) * 1000)

    # ── Step 5: Merge results ─────────────────────────────────
    all_detected = _collect_detected(
        nlp_result, pricing_result, behavioral_result, visual_result
    )
    total_detected = len(all_detected)

    # Extract cross-agent enrichments stashed by helpers
    financial_impact = getattr(pricing_result,    "_financial_impact", {})
    severity_score   = getattr(behavioral_result, "_severity_score",   0.0)
    severity_label   = getattr(behavioral_result, "_severity_label",   "none")

    total_duration_ms = int((time.perf_counter() - wall_start) * 1000)

    log.info(
        "scan_complete",
        total_detected    = total_detected,
        total_patches     = prevention_result.get("total_patches", 0),
        total_duration_ms = total_duration_ms,
    )

    return ScanResponse(
        scrape_id                 = scrape_id,
        session_id                = session_id,
        url                       = url_str,
        page_type                 = page_type,
        nlp                       = nlp_result,
        pricing                   = pricing_result,
        behavioral                = behavioral_result,
        visual                    = visual_result,
        total_detected            = total_detected,
        all_detected_patterns     = all_detected,
        financial_impact          = financial_impact,
        behavioral_severity_score = severity_score,
        behavioral_severity_label = severity_label,
        prevention                = prevention_result,
        scrape_duration_ms        = scrape_duration_ms,
        agents_duration_ms        = agents_duration_ms,
        prevention_duration_ms    = prevention_duration_ms,
        total_duration_ms         = total_duration_ms,
    )