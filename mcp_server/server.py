"""
mcp_server/server.py
─────────────────────────────────────────────────────────────────
MCP Server — fully wired for Phase 2.
"""
from __future__ import annotations

import json

import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from backend.cache.redis_client import get_redis_client
from backend.cache.session_store import SessionStore
from backend.scraper.browser_pool import close_browser_pool, init_browser_pool
from backend.scraper.playwright_scraper import scrape
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
    await get_redis_client()
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


# ── Scrape test endpoint ──────────────────────────────────────
class ScrapeTestRequest(BaseModel):
    url: str = "https://example.com"
    session_id: str = "test-session"


@app.post("/scrape-test")
async def scrape_test(body: ScrapeTestRequest) -> dict:
    """
    Direct REST endpoint to test the scraper without MCP protocol.
    """
    result = await scrape(url=body.url, session_id=body.session_id)

    redis = await get_redis_client()
    store = SessionStore(redis)
    await store.save_scrape(result)

    return {
        "scrape_id":    result.scrape_id,
        "session_id":   result.session_id,
        "page_type":    result.page_type.value,
        "title":        result.title,
        "final_url":    result.final_url,
        "duration_ms":  result.scrape_duration_ms,
        "screenshot_kb": len(result.screenshot_b64 or "") // 1024,
        "counts": {
            "buttons":          len(result.buttons),
            "forms":            len(result.forms),
            "prices":           len(result.prices),
            "overlays":         len(result.overlays),
            "timers":           len(result.timers),
            "hidden":           len(result.hidden_elements),
            "links":            len(result.links),
            "mutations":        len(result.dom_mutations),
            "network_reqs":     len(result.network_requests),
            "auto_popups":      result.auto_popup_count,
            "text_elements": len(result.text_elements),
        },
        "sample_buttons": [
            {"text": b.text, "in_modal": b.is_in_modal, "is_close": b.is_close_button}
            for b in result.buttons[:5]
        ],
        "sample_prices": [
            {"text": p.text, "amount": p.amount, "location": p.location}
            for p in result.prices[:5]
        ],
        "sample_overlays": [
            {
                "type": o.overlay_type,
                "autonomous": o.appeared_autonomously,
                "coverage_pct": o.viewport_coverage_pct,
                "text": o.text[:100],
            }
            for o in result.overlays[:3]
        ],
        "redis_keys": {
            "nlp":        f"dg:nlp:{result.scrape_id}",
            "visual":     f"dg:visual:{result.scrape_id}",
            "pricing":    f"dg:pricing:{result.session_id}:{result.scrape_id}",
            "behavioral": f"dg:behavioral:{result.session_id}:{result.scrape_id}",
            "screenshot": f"dg:scrape:{result.scrape_id}:screenshot",
            "text":       f"dg:scrape:{result.scrape_id}:text",
        },
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
    Scrape a web page using Playwright and store results in Redis.
    Returns JSON with scrape_id, page_type, agent_keys, summary.
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
    agent must be one of: nlp | visual | pricing | behavioral | screenshot
    """
    redis = await get_redis_client()

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
            "message": f"No payload for agent={agent} scrape_id={scrape_id}.",
        })

    return raw


# ═══════════════════════════════════════════════════════════════
#  MCP TOOL: get_session_history
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def get_session_history(session_id: str) -> str:
    """Return the ordered scrape history for a session."""
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
    """Persist a completed detection + prevention result to Redis (stub)."""
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
    """Vector search for similar dark patterns (Qdrant stub — Phase 4)."""
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
        log_level="debug" if settings.debug else "info",
    )