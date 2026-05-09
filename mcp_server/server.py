"""
mcp_server/server.py
─────────────────────────────────────────────────────────────────
MCP Server — fully wired for Phase 2.

All five tools are registered:
  scrape_page           → Playwright scraper + Redis session store
  get_agent_payload     → Retrieve any agent's payload from Redis
  get_session_history   → Return the scrape timeline for a session
  store_detection       → Persist agent detection results (stub → Phase 4)
  fetch_similar_patterns→ Qdrant vector search (stub → Phase 4)
"""
from __future__ import annotations

import json
from typing import Any

import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from backend.cache.redis_client import get_redis_client
from backend.cache.session_store import SessionStore
from backend.scraper.browser_pool import close_browser_pool, init_browser_pool
from mcp_server.tools.scrape_tool import handle_scrape_page
from config import get_settings

import structlog

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── FastAPI app ───────────────────────────────────────────────
app = FastAPI(
    title="Dark Guard MCP Server",
    version="0.2.0",
    description="MCP coordination server — browser scraping + agent routing",
)

# ── FastMCP instance ──────────────────────────────────────────
mcp = FastMCP("dark-guard-mcp")


# ── Lifespan ──────────────────────────────────────────────────
@app.on_event("startup")
async def startup() -> None:
    logger.info("mcp_server_starting", port=settings.mcp_port)
    await init_browser_pool()
    await get_redis_client()      # warm connection pool
    logger.info("mcp_server_ready")


@app.on_event("shutdown")
async def shutdown() -> None:
    logger.info("mcp_server_stopping")
    await close_browser_pool()


# ── Health routes ─────────────────────────────────────────────
@app.get("/")
async def root() -> dict:
    return {"message": "Dark Guard MCP Server", "version": "0.2.0"}


@app.get("/health")
async def health() -> dict:
    try:
        redis = await get_redis_client()
        await redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": "ok" if redis_ok else "error",
    }


# ═══════════════════════════════════════════════════════════════
#  MCP TOOL: scrape_page
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def scrape_page(
    url: str,
    session_id: str,
    force: bool = False,
) -> str:
    """
    Scrape a web page using Playwright.

    Performs JS-rendered scraping, extracts all dark-pattern-relevant
    data (buttons, forms, prices, overlays, timers, hidden elements,
    network requests, DOM mutations), stores everything in Redis
    keyed by session, and returns Redis keys for each agent's payload.

    Args:
        url        : Full URL to scrape (must start with http/https)
        session_id : Browser tab session ID — links scrapes in a journey
        force      : Set True to bypass cache and force a fresh scrape

    Returns:
        JSON string with scrape_id, page_type, agent_keys, summary
    """
    result = await handle_scrape_page({
        "url": url,
        "session_id": session_id,
        "force": force,
    })
    return json.dumps(result)


# ═══════════════════════════════════════════════════════════════
#  MCP TOOL: get_agent_payload
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def get_agent_payload(
    agent: str,
    scrape_id: str,
    session_id: str,
) -> str:
    """
    Retrieve a pre-built agent payload from Redis.

    After scrape_page completes, each agent's input payload is already
    stored in Redis. Call this to fetch the data for a specific agent.

    Args:
        agent      : One of "nlp" | "visual" | "pricing" | "behavioral"
        scrape_id  : The scrape_id returned by scrape_page
        session_id : The session_id used when scraping

    Returns:
        JSON string of the agent-specific payload
    """
    redis = await get_redis_client()
    store = SessionStore(redis)

    key_map = {
        "nlp":        f"dg:nlp:{scrape_id}",
        "visual":     f"dg:visual:{scrape_id}",
        "pricing":    f"dg:pricing:{session_id}:{scrape_id}",
        "behavioral": f"dg:behavioral:{session_id}:{scrape_id}",
        "screenshot": f"dg:scrape:{scrape_id}:screenshot",
    }

    key = key_map.get(agent)
    if not key:
        return json.dumps({"error": f"Unknown agent: {agent}. Must be one of {list(key_map)}"})

    raw = await redis.get(key)
    if not raw:
        return json.dumps({
            "error": "payload_not_found",
            "message": f"No payload for agent={agent} scrape_id={scrape_id}. "
                       "It may have expired (TTL=10min) or the scrape failed.",
        })

    return raw   # already JSON-serialised from save_scrape


# ═══════════════════════════════════════════════════════════════
#  MCP TOOL: get_session_history
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def get_session_history(session_id: str) -> str:
    """
    Return the scrape history for a session.

    Returns an ordered list of scrape metadata objects — one per page
    the user visited in this tab. Used by the Orchestrator to decide
    routing (e.g., is there a preceding product page for price comparison?).

    Args:
        session_id : The session ID

    Returns:
        JSON array of scrape metadata objects (url, page_type, timestamp, etc.)
    """
    redis = await get_redis_client()
    store = SessionStore(redis)

    scrape_ids = await store.get_session_scrape_ids(session_id)
    if not scrape_ids:
        return json.dumps({"session_id": session_id, "scrapes": []})

    metas = []
    for sid in scrape_ids:
        meta = await store.get_scrape_meta(sid)
        if meta:
            metas.append(meta)

    return json.dumps({"session_id": session_id, "scrapes": metas})


# ═══════════════════════════════════════════════════════════════
#  MCP TOOL: store_detection  (stub — Phase 4)
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def store_detection(
    scrape_id: str,
    session_id: str,
    detection_result: dict,
    prevention_result: dict,
) -> str:
    """
    Persist a completed detection + prevention result.
    Stores in SQLite (permanent record) and Qdrant (vector index).

    NOTE: Full implementation in Phase 4.
    Currently stores result in Redis as a temporary record.

    Args:
        scrape_id        : Scrape this detection belongs to
        session_id       : Session ID
        detection_result : Dict of NLP/Visual/Pricing/Behavioral results
        prevention_result: Dict of patch instructions from Prevention Agent
    """
    redis = await get_redis_client()
    combined = {
        "scrape_id": scrape_id,
        "session_id": session_id,
        "detection": detection_result,
        "prevention": prevention_result,
    }
    await redis.setex(
        f"dg:result:{scrape_id}",
        3600,
        json.dumps(combined, default=str),
    )
    logger.info("detection_stored_redis", scrape_id=scrape_id)
    return json.dumps({"stored": True, "scrape_id": scrape_id, "backend": "redis_stub"})


# ═══════════════════════════════════════════════════════════════
#  MCP TOOL: fetch_similar_patterns  (stub — Phase 4)
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def fetch_similar_patterns(
    text: str,
    top_k: int = 5,
    pattern_code: str | None = None,
) -> str:
    """
    Find similar previously-detected dark patterns using vector search.
    Used by NLP Agent to enrich its prompt with real historical examples.

    NOTE: Full Qdrant implementation in Phase 4.
    Currently returns an empty matches list.

    Args:
        text         : Text snippet to search for similar patterns
        top_k        : Number of results to return
        pattern_code : Optional filter e.g. "DP01" to restrict to one type
    """
    logger.info("fetch_similar_stub", text_len=len(text), pattern=pattern_code)
    return json.dumps({
        "matches": [],
        "note": "Qdrant integration pending (Phase 4)",
    })


# ── Mount MCP routes and run ──────────────────────────────────
app.mount("/mcp", mcp.sse_app())


if __name__ == "__main__":
    uvicorn.run(
        "mcp_server.server:app",
        host=settings.mcp_host,
        port=settings.mcp_port,
        reload=settings.is_development,
        log_level=settings.debug and "debug" or "info",
    )