"""
backend/api/v1/scan.py
─────────────────────────────────────────────────────────────────
Full orchestration endpoint for Dark Guard AI.

Flow:
    POST /api/v1/scan
        │
        ├─ 1. Validate ScanRequest (url + session_id)
        ├─ 2. Scrape page with Playwright  →  ScrapedPage
        ├─ 3. Persist all 4 agent payloads to Redis (SessionStore.save_scrape)
        ├─ 4. Run Orchestrator Agent (handles routing, dispatch, synthesis)
        └─ 5. Return OrchestratorReport as JSON response
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

from agents.orchestrator_agent.models import OrchestratorReport
from agents.orchestrator_agent.runner import run_orchestrator
from backend.cache.redis_client import get_redis_client
from backend.cache.session_store import SessionStore
from backend.scraper.playwright_scraper import scrape

logger = structlog.get_logger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
#  REQUEST MODEL
# ═══════════════════════════════════════════════════════════════

class ScanRequest(BaseModel):
    """
    Payload sent by the browser extension to trigger a full scan.

    session_id ties multiple page scrapes together so cross-page
    detectors (Pricing, Behavioral) can compare the current page
    against previous pages in the same browsing session.

    If the extension does not yet have a session_id, omit the field —
    a fresh UUID is generated automatically and returned in the response
    so the extension can store it for subsequent requests.
    """
    url: HttpUrl
    session_id: str | None = Field(
        default=None,
        description="Browsing-session ID. Auto-generated if omitted.",
    )


# ═══════════════════════════════════════════════════════════════
#  ENDPOINT
# ═══════════════════════════════════════════════════════════════

@router.post(
    "/scan",
    response_model=OrchestratorReport,
    status_code=status.HTTP_200_OK,
    summary="Scan a URL for dark patterns",
    description=(
        "Scrapes the given URL with Playwright, then runs the Orchestrator Agent "
        "which intelligently routes to NLP, Pricing, Behavioral, and Visual "
        "detection agents based on page type. Returns a unified detection report."
    ),
)
async def scan_endpoint(request: ScanRequest) -> OrchestratorReport:
    wall_start = time.perf_counter()

    # ── Resolve session_id ────────────────────────────────────
    session_id: str = request.session_id or str(uuid.uuid4())
    url_str:    str = str(request.url)

    log = logger.bind(url=url_str, session_id=session_id)
    log.info("scan_request_received")

    # ── Step 1: Scrape ────────────────────────────────────────
    scrape_start = time.perf_counter()
    try:
        scraped_page = await scrape(url=url_str, session_id=session_id)
    except Exception as exc:
        log.error("scrape_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to scrape URL: {exc}",
        ) from exc

    scrape_duration_ms = int((time.perf_counter() - scrape_start) * 1000)
    scrape_id = scraped_page.scrape_id
    page_type = scraped_page.page_type.value

    log.info(
        "scrape_complete",
        scrape_id=scrape_id,
        page_type=page_type,
        duration_ms=scrape_duration_ms,
    )

    # ── Step 2: Persist to Redis ──────────────────────────────
    # Builds all 4 agent payloads and writes them in one Redis pipeline.
    # Orchestrator agents read their payloads from Redis by scrape_id.
    # This MUST complete before run_orchestrator is called.
    try:
        redis_client = await get_redis_client()
        store = SessionStore(redis_client)
        await store.save_scrape(scraped_page)
    except Exception as exc:
        log.error("session_store_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist scrape data: {exc}",
        ) from exc

    log.info("scrape_persisted_to_redis", scrape_id=scrape_id)

    # ── Step 3: Run Orchestrator ──────────────────────────────
    # The orchestrator handles all routing, agent dispatch,
    # confidence re-runs, deduplication, scoring, and synthesis.
    try:
        report: OrchestratorReport = await run_orchestrator(
            scrape_id=scrape_id,
            session_id=session_id,
            url=url_str,
            page_type=page_type,
        )
    except Exception as exc:
        log.error("orchestrator_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Orchestrator failed: {exc}",
        ) from exc

    total_duration_ms = int((time.perf_counter() - wall_start) * 1000)
    report.scan_duration_ms = total_duration_ms

    log.info(
        "scan_complete",
        total_detected=report.total_detected,
        severity=report.overall_severity_label,
        score=report.overall_severity_score,
        total_duration_ms=total_duration_ms,
    )

    return report
