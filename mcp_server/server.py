"""
mcp_server/server.py
─────────────────────────────────────────────────────────────────
MCP Server — fully wired for Phase 2 + NLP Agent + Pricing Agent.
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
    version="0.3.0",
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
    return {"message": "Dark Guard MCP Server", "version": "0.3.0"}


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
#  REST: /scrape-test
# ═══════════════════════════════════════════════════════════════

class ScrapeTestRequest(BaseModel):
    url: str = "https://example.com"
    session_id: str = "test-session"


@app.post("/scrape-test")
async def scrape_test(body: ScrapeTestRequest) -> dict:
    """
    Direct REST endpoint to test the scraper without MCP protocol.
    Scrapes the given URL, stores all data in Redis, and returns
    a summary with counts, samples, and Redis key references.
    """
    result = await scrape(url=body.url, session_id=body.session_id)

    redis = await get_redis_client()
    store = SessionStore(redis)
    await store.save_scrape(result)

    return {
        "scrape_id":     result.scrape_id,
        "session_id":    result.session_id,
        "page_type":     result.page_type.value,
        "title":         result.title,
        "final_url":     result.final_url,
        "duration_ms":   result.scrape_duration_ms,
        "screenshot_kb": len(result.screenshot_b64 or "") // 1024,
        "counts": {
            "buttons":       len(result.buttons),
            "forms":         len(result.forms),
            "prices":        len(result.prices),
            "overlays":      len(result.overlays),
            "timers":        len(result.timers),
            "hidden":        len(result.hidden_elements),
            "links":         len(result.links),
            "mutations":     len(result.dom_mutations),
            "network_reqs":  len(result.network_requests),
            "auto_popups":   result.auto_popup_count,
            "text_elements": len(result.text_elements),
        },
        "sample_buttons": [
            {
                "text":     b.text[:120],
                "in_modal": b.is_in_modal,
                "is_close": b.is_close_button,
            }
            for b in result.buttons[:5]
        ],
        "sample_prices": [
            {
                "text":     p.text[:80],
                "amount":   p.amount,
                "location": p.location,
            }
            for p in result.prices[:5]
        ],
        "sample_overlays": [
            {
                "type":         o.overlay_type,
                "autonomous":   o.appeared_autonomously,
                "coverage_pct": o.viewport_coverage_pct,
                "text":         o.text[:100],
            }
            for o in result.overlays[:3]
        ],
        "sample_text_elements": [
            {
                "tag":      t.tag,
                "text":     t.text[:120],
                "location": t.location,
                "visible":  t.is_visible,
                "fixed":    t.is_in_fixed,
            }
            for t in result.text_elements[:20]
        ],
        "text_by_location": {
            loc: [
                t.text[:100]
                for t in result.text_elements
                if t.location == loc
            ][:5]
            for loc in {t.location for t in result.text_elements}
        },
        "redis_keys": {
            "nlp":        f"dg:nlp:{result.scrape_id}",
            "visual":     f"dg:visual:{result.scrape_id}",
            "pricing":    f"dg:pricing:{result.session_id}:{result.scrape_id}",
            "behavioral": f"dg:behavioral:{result.session_id}:{result.scrape_id}",
            "screenshot": f"dg:scrape:{result.scrape_id}:screenshot",
            "text":       f"dg:scrape:{result.scrape_id}:text",
            "dom":        f"dg:scrape:{result.scrape_id}:dom",
        },
    }


# ═══════════════════════════════════════════════════════════════
#  REST: /detect-test  (NLP Agent)
# ═══════════════════════════════════════════════════════════════

class DetectTestRequest(BaseModel):
    scrape_id: str
    session_id: str = "test-session"


@app.post("/detect-test")
async def detect_test(body: DetectTestRequest) -> dict:
    """
    Run the NLP Agent on an already-scraped page.
    Detects: False Urgency, Confirm Shaming, Disguised Ads, Trick Question.

    Step 1: POST /scrape-test with any URL → copy scrape_id
    Step 2: POST /detect-test with that scrape_id
    """
    from agents.nlp_agent.runner import run_nlp_agent

    try:
        result = await run_nlp_agent(
            scrape_id=body.scrape_id,
            session_id=body.session_id,
        )
        return {
            "scrape_id":      result.scrape_id,
            "url":            result.url,
            "page_type":      result.page_type,
            "total_detected": result.total_detected,
            "duration_ms":    result.detection_duration_ms,
            "patterns": [
                {
                    "code":       p.pattern_code
                        if isinstance(p.pattern_code, str)
                        else p.pattern_code.value,
                    "name":       p.pattern_name,
                    "detected":   p.detected,
                    "confidence": round(p.confidence, 3),
                    "evidence": [
                        {
                            "text":     e.text[:200],
                            "location": e.location,
                            "reason":   e.reason,
                        }
                        for e in p.evidence
                    ],
                    "error": p.error,
                }
                for p in result.patterns
            ],
        }
    except KeyError as exc:
        return {"error": "not_found", "message": str(exc)}
    except Exception as exc:
        logger.error("detect_test_error", error=str(exc), exc_info=True)
        return {"error": "detection_failed", "message": str(exc)}


# ═══════════════════════════════════════════════════════════════
#  REST: /pricing-detect-test  (Pricing Agent)
# ═══════════════════════════════════════════════════════════════

class PricingDetectRequest(BaseModel):
    scrape_id: str
    session_id: str = "test-session"


@app.post("/pricing-detect-test")
async def pricing_detect_test(body: PricingDetectRequest) -> dict:
    """
    Run the Pricing Agent on an already-scraped cart/checkout page.
    Detects: Drip Pricing, Bait and Switch.

    Best test flow:
      Step 1: POST /scrape-test { url: <product-page>, session_id: "X" }
      Step 2: POST /scrape-test { url: <cart-page>,    session_id: "X" }
      Step 3: POST /pricing-detect-test { scrape_id: <cart-scrape-id>, session_id: "X" }
    """
    from agents.pricing_agent.runner import run_pricing_agent

    try:
        result = await run_pricing_agent(
            scrape_id=body.scrape_id,
            session_id=body.session_id,
        )
        return result
    except KeyError as exc:
        return {"error": "not_found", "message": str(exc)}
    except Exception as exc:
        logger.error("pricing_detect_error", error=str(exc), exc_info=True)
        return {"error": "detection_failed", "message": str(exc)}


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

    Performs JS-rendered scraping, extracts all dark-pattern-relevant
    data (buttons, forms, prices, overlays, timers, hidden elements,
    text elements, network requests, DOM mutations), stores everything
    in Redis keyed by session, and returns Redis keys for each agent.

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
        agent      : One of nlp | visual | pricing | behavioral | screenshot | text | dom
        scrape_id  : The scrape_id returned by scrape_page
        session_id : The session_id used when scraping

    Returns:
        JSON string of the agent-specific payload
    """
    redis = await get_redis_client()

    key_map = {
        "nlp":        f"dg:nlp:{scrape_id}",
        "visual":     f"dg:visual:{scrape_id}",
        "pricing":    f"dg:pricing:{session_id}:{scrape_id}",
        "behavioral": f"dg:behavioral:{session_id}:{scrape_id}",
        "screenshot": f"dg:scrape:{scrape_id}:screenshot",
        "text":       f"dg:scrape:{scrape_id}:text",
        "dom":        f"dg:scrape:{scrape_id}:dom",
    }

    key = key_map.get(agent)
    if not key:
        return json.dumps({
            "error": f"Unknown agent: '{agent}'. Must be one of: {list(key_map)}"
        })

    raw = await redis.get(key)
    if not raw:
        return json.dumps({
            "error": "payload_not_found",
            "message": (
                f"No payload for agent='{agent}' scrape_id='{scrape_id}'. "
                "It may have expired (TTL=10min) or the scrape failed."
            ),
        })

    return raw


# ═══════════════════════════════════════════════════════════════
#  MCP TOOL: get_session_history
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def get_session_history(session_id: str) -> str:
    """
    Return the ordered scrape history for a session.

    Returns a list of scrape metadata objects — one per page visited
    in this tab. Used by the Orchestrator to decide routing (e.g.,
    is there a preceding product page for price comparison?).

    Args:
        session_id : The session ID

    Returns:
        JSON with session_id and ordered list of scrape metadata
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
#  MCP TOOL: run_nlp_detection
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def run_nlp_detection(scrape_id: str, session_id: str) -> str:
    """
    Run NLP dark pattern detection on a scraped page.
    Detects: False Urgency (DP01), Confirm Shaming (DP02),
             Disguised Ads (DP03), Trick Question (DP04).

    The scrape_id must exist in Redis from a prior scrape_page call.
    Returns JSON with per-pattern detection results and evidence.

    Args:
        scrape_id  : ID from a completed scrape_page call
        session_id : Session ID used during scraping
    """
    from agents.nlp_agent.runner import run_nlp_agent

    try:
        result = await run_nlp_agent(
            scrape_id=scrape_id,
            session_id=session_id,
        )
        return result.model_dump_json()
    except Exception as exc:
        logger.error("mcp_nlp_detection_error", error=str(exc), exc_info=True)
        return json.dumps({"error": str(exc)})


# ═══════════════════════════════════════════════════════════════
#  MCP TOOL: run_pricing_detection
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def run_pricing_detection(scrape_id: str, session_id: str) -> str:
    """
    Run Pricing Agent dark pattern detection on a scraped cart/checkout page.
    Detects: Drip Pricing (DP05), Bait and Switch (DP06).

    Requires the scrape_id of a CART, CHECKOUT, or PAYMENT page.
    For bait-and-switch detection, a prior product page scrape in the
    same session is needed to compare prices.

    Args:
        scrape_id  : ID from a completed scrape_page call (cart/checkout page)
        session_id : Session ID — must match the session used for both
                     the product page and cart page scrapes
    """
    from agents.pricing_agent.runner import run_pricing_agent

    try:
        result = await run_pricing_agent(
            scrape_id=scrape_id,
            session_id=session_id,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("mcp_pricing_detection_error", error=str(exc), exc_info=True)
        return json.dumps({"error": str(exc)})


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

    NOTE: Full SQLite + Qdrant implementation in Phase 4.
    Currently stores result in Redis as a temporary record (TTL 1hr).

    Args:
        scrape_id        : Scrape this detection belongs to
        session_id       : Session ID
        detection_result : Merged dict of all agent detection results
        prevention_result: Dict of patch instructions from Prevention Agent
    """
    redis = await get_redis_client()
    combined = {
        "scrape_id":  scrape_id,
        "session_id": session_id,
        "detection":  detection_result,
        "prevention": prevention_result,
    }
    await redis.setex(
        f"dg:result:{scrape_id}",
        3600,
        json.dumps(combined, default=str),
    )
    logger.info("detection_stored_redis", scrape_id=scrape_id)
    return json.dumps({
        "stored":  True,
        "scrape_id": scrape_id,
        "backend": "redis_stub",
    })


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

    NOTE: Full Qdrant implementation in Phase 4.
    Currently returns an empty matches list.

    Args:
        text         : Text snippet to find similar patterns for
        top_k        : Number of results to return (default 5)
        pattern_code : Optional filter e.g. "DP01" to restrict to one type
    """
    logger.info(
        "fetch_similar_stub",
        text_len=len(text),
        pattern=pattern_code,
    )
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