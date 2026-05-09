"""
mcp_server/tools/scrape_tool.py
─────────────────────────────────────────────────────────────────
MCP tool handler for scrape_page.

This is the full implementation that:
  1. Checks Redis for a cached result (fast path)
  2. Acquires a distributed lock (prevent duplicate scrapes)
  3. Runs the Playwright scraper
  4. Persists all data to Redis via SessionStore
  5. Returns the routing payload to the calling agent
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from backend.cache.redis_client import get_redis_client
from backend.cache.session_store import SessionStore
from backend.scraper.playwright_scraper import scrape
from backend.scraper.models import PageType

logger = structlog.get_logger(__name__)


async def handle_scrape_page(args: dict[str, Any]) -> dict[str, Any]:
    """
    MCP tool handler: scrape_page

    Args:
        url        (str, required)  : URL to scrape
        session_id (str, required)  : Session ID from the browser tab
        force      (bool, optional) : Bypass cache and force fresh scrape

    Returns:
        dict with keys:
          scrape_id    : ID of this scrape
          session_id   : Echo of session_id
          page_type    : Classified page type
          url          : Final URL (after redirects)
          agent_keys   : Dict mapping agent name → Redis key for its payload
          summary      : Lightweight stats dict
          cached       : Whether result was served from cache
    """
    url = args.get("url", "").strip()
    session_id = args.get("session_id", "").strip()
    force = args.get("force", False)

    if not url:
        return {"error": "url is required"}
    if not session_id:
        return {"error": "session_id is required"}

    redis = await get_redis_client()
    store = SessionStore(redis)

    log = logger.bind(url=url, session_id=session_id)

    # ── Fast path: check if session already has a recent scrape of this URL
    if not force:
        cached = await _find_cached_scrape(store, session_id, url)
        if cached:
            log.info("mcp_scrape_cache_hit", scrape_id=cached["scrape_id"])
            cached["cached"] = True
            return cached

    # ── Acquire distributed lock ──────────────────────────────
    lock_key = f"{session_id}:{url}"
    acquired = await store.acquire_lock(lock_key)
    if not acquired:
        log.warning("mcp_scrape_lock_busy")
        return {
            "error": "scrape_in_progress",
            "message": "A scrape for this URL+session is already running. Retry in 5s.",
        }

    try:
        log.info("mcp_scrape_starting")

        # ── Run Playwright scraper ────────────────────────────
        scraped_page = await scrape(url=url, session_id=session_id)

        # ── Persist all data to Redis ─────────────────────────
        await store.save_scrape(scraped_page)

        # ── Build response payload ────────────────────────────
        response = _build_response(scraped_page, cached=False)
        log.info(
            "mcp_scrape_complete",
            scrape_id=scraped_page.scrape_id,
            page_type=scraped_page.page_type.value,
            duration_ms=scraped_page.scrape_duration_ms,
        )
        return response

    except Exception as exc:
        log.error("mcp_scrape_error", error=str(exc), exc_info=True)
        return {"error": "scrape_failed", "message": str(exc)}

    finally:
        await store.release_lock(lock_key)


async def _find_cached_scrape(
    store: SessionStore, session_id: str, url: str
) -> dict | None:
    """
    Check if the session's most recent scrape was for this URL.
    Returns the response dict if a recent matching scrape exists.
    """
    scrape_ids = await store.get_session_scrape_ids(session_id)
    if not scrape_ids:
        return None

    # Check the last scrape
    last_id = scrape_ids[-1]
    meta = await store.get_scrape_meta(last_id)
    if not meta:
        return None

    if meta.get("url") == url or meta.get("final_url") == url:
        return {
            "scrape_id": last_id,
            "session_id": session_id,
            "page_type": meta.get("page_type", "OTHER"),
            "url": meta.get("final_url", url),
            "agent_keys": {
                "nlp":        f"dg:nlp:{last_id}",
                "visual":     f"dg:visual:{last_id}",
                "pricing":    f"dg:pricing:{session_id}:{last_id}",
                "behavioral": f"dg:behavioral:{session_id}:{last_id}",
                "screenshot": f"dg:scrape:{last_id}:screenshot",
            },
            "summary": {
                "button_count":     meta.get("button_count", 0),
                "overlay_count":    meta.get("overlay_count", 0),
                "price_count":      meta.get("price_count", 0),
                "auto_popup_count": meta.get("auto_popup_count", 0),
                "scrape_duration_ms": meta.get("scrape_duration_ms", 0),
            },
        }
    return None


def _build_response(page: Any, cached: bool) -> dict:
    """Build the standard response dict from a ScrapedPage."""
    scrape_id  = page.scrape_id
    session_id = page.session_id
    return {
        "scrape_id":  scrape_id,
        "session_id": session_id,
        "page_type":  page.page_type.value,
        "url":        page.final_url,
        "cached":     cached,
        "agent_keys": {
            "nlp":        f"dg:nlp:{scrape_id}",
            "visual":     f"dg:visual:{scrape_id}",
            "pricing":    f"dg:pricing:{session_id}:{scrape_id}",
            "behavioral": f"dg:behavioral:{session_id}:{scrape_id}",
            "screenshot": f"dg:scrape:{scrape_id}:screenshot",
        },
        "summary": {
            "button_count":      len(page.buttons),
            "overlay_count":     len(page.overlays),
            "price_count":       len(page.prices),
            "timer_count":       len(page.timers),
            "form_count":        len(page.forms),
            "hidden_count":      len(page.hidden_elements),
            "auto_popup_count":  page.auto_popup_count,
            "auto_cart_mutations": len(page.auto_cart_mutations),
            "redirect_trap_count": len([l for l in page.links if l.domain_mismatch]),
            "scrape_duration_ms":  page.scrape_duration_ms,
        },
    }