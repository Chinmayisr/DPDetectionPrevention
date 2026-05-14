"""
mcp_server/server.py
─────────────────────────────────────────────────────────────────
MCP Server — fully wired for all 13 dark patterns + Prevention Agent.

REST test endpoints:
  GET  /                              → root + pattern catalogue
  GET  /health                        → health check
  POST /scrape-test                   → scrape URL + store in Redis
  POST /detect-test                   → NLP Agent (DP01–DP04)
  POST /pricing-detect-test           → Pricing Agent (DP05–DP06)
  POST /behavioral-detect-test        → Behavioral Agent (DP07–DP11, DP13)
  POST /visual-detect-test            → Visual Agent (DP03, DP12)
  POST /prevention-test               → Prevention Agent (all 13 patterns)

MCP tools (callable by LangGraph agents):
  scrape_page
  get_agent_payload
  get_session_history
  run_nlp_detection
  run_pricing_detection
  run_behavioral_detection
  run_visual_detection
  run_prevention
  store_detection
  fetch_similar_patterns
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
    version="0.6.0",
    description=(
        "MCP coordination server — browser scraping + "
        "NLP + Pricing + Behavioral + Visual dark pattern detection "
        "+ Prevention. Covers all 13 dark pattern types (DP01–DP13)."
    ),
)

# ── FastMCP instance ──────────────────────────────────────────
mcp = FastMCP("dark-guard-mcp")


# ── Lifespan ──────────────────────────────────────────────────
@app.on_event("startup")
async def startup() -> None:
    logger.info("mcp_server_starting", port=settings.mcp_port)
    
    await get_redis_client()
    logger.info("mcp_server_ready")


@app.on_event("shutdown")
async def shutdown() -> None:
    logger.info("mcp_server_stopping")
    await close_browser_pool()


# ═════════════════════════════════════════════════════════════
#  HEALTH
# ═════════════════════════════════════════════════════════════

@app.get("/")
async def root() -> dict:
    return {
        "message" : "Dark Guard MCP Server",
        "version" : "0.6.0",
        "agents"  : ["nlp", "pricing", "behavioral", "visual", "prevention"],
        "patterns": {
            "DP01": "False Urgency",
            "DP02": "Confirm Shaming",
            "DP03": "Disguised Ads",
            "DP04": "Trick Question",
            "DP05": "Drip Pricing",
            "DP06": "Bait and Switch",
            "DP07": "Basket Sneaking",
            "DP08": "Subscription Trap",
            "DP09": "Nagging",
            "DP10": "SaaS Billing",
            "DP11": "Rogue and Malicious Content",
            "DP12": "Interface Interference",
            "DP13": "Forced Action",
        },
    }


@app.get("/health")
async def health() -> dict:
    redis_ok = False
    try:
        redis = await get_redis_client()
        await redis.ping()
        redis_ok = True
    except Exception:
        pass
    return {
        "status": "ok" if redis_ok else "degraded",
        "redis" : redis_ok,
    }


# ═════════════════════════════════════════════════════════════
#  REQUEST MODELS
# ═════════════════════════════════════════════════════════════

class ScrapeRequest(BaseModel):
    url       : str
    session_id: str = "test-session"


class DetectRequest(BaseModel):
    scrape_id : str
    session_id: str = "test-session"


# ═════════════════════════════════════════════════════════════
#  REST TEST ENDPOINTS
# ═════════════════════════════════════════════════════════════

@app.post("/scrape-test")
async def scrape_test(body: ScrapeRequest) -> dict:
    """
    Scrape a URL and store the full payload in Redis.
    Returns the scrape_id needed by all detection endpoints.
    """
    try:
        scraped_page = await scrape(url=body.url, session_id=body.session_id)
        redis        = await get_redis_client()
        store        = SessionStore(redis)
        await store.save_scrape(scraped_page)
        return {
            "scrape_id"  : scraped_page.scrape_id,
            "session_id" : body.session_id,
            "url"        : body.url,
            "page_type"  : scraped_page.page_type.value,
        }
    except Exception as exc:
        logger.error("scrape_test_error", error=str(exc), exc_info=True)
        return {"error": str(exc)}


@app.post("/detect-test")
async def detect_test(body: DetectRequest) -> dict:
    """
    Run the NLP Agent on an already-scraped page.
    Detects: False Urgency (DP01), Confirm Shaming (DP02),
             Disguised Ads (DP03), Trick Question (DP04).
    """
    from agents.nlp_agent.runner import run_nlp_agent
    try:
        result = await run_nlp_agent(
            scrape_id  = body.scrape_id,
            session_id = body.session_id,
        )
        return result
    except Exception as exc:
        logger.error("detect_test_error", error=str(exc), exc_info=True)
        return {"error": str(exc)}


@app.post("/pricing-detect-test")
async def pricing_detect_test(body: DetectRequest) -> dict:
    """
    Run the Pricing Agent on an already-scraped page.
    Detects: Drip Pricing (DP05), Bait and Switch (DP06).

    For best results:
      1. POST /scrape-test with a product page URL (same session_id)
      2. POST /scrape-test with the cart/checkout URL (same session_id)
      3. POST /pricing-detect-test with the cart scrape_id
    """
    from agents.pricing_agent.runner import run_pricing_agent
    try:
        result = await run_pricing_agent(
            scrape_id  = body.scrape_id,
            session_id = body.session_id,
        )
        return result
    except Exception as exc:
        logger.error("pricing_detect_test_error", error=str(exc), exc_info=True)
        return {"error": str(exc)}


@app.post("/behavioral-detect-test")
async def behavioral_detect_test(body: DetectRequest) -> dict:
    """
    Run the Behavioral Agent on an already-scraped page.
    Detects: Basket Sneaking (DP07), Subscription Trap (DP08),
             Nagging (DP09), SaaS Billing (DP10),
             Rogue/Malicious Content (DP11), Forced Action (DP13).
    """
    from agents.behavioral_agent.runner import run_behavioral_agent
    try:
        result = await run_behavioral_agent(
            scrape_id  = body.scrape_id,
            session_id = body.session_id,
        )
        return result
    except Exception as exc:
        logger.error("behavioral_detect_test_error", error=str(exc), exc_info=True)
        return {"error": str(exc)}


@app.post("/visual-detect-test")
async def visual_detect_test(body: DetectRequest) -> dict:
    """
    Run the Visual Agent on an already-scraped page.
    Detects: Disguised Ads (DP03), Interface Interference (DP12).
    Requires a screenshot to have been stored by the scraper.
    """
    from agents.visual_agent.runner import run_visual_agent
    try:
        result = await run_visual_agent(
            scrape_id  = body.scrape_id,
            session_id = body.session_id,
        )
        return result
    except Exception as exc:
        logger.error("visual_detect_test_error", error=str(exc), exc_info=True)
        return {"error": str(exc)}


@app.post("/prevention-test")
async def prevention_test(body: DetectRequest) -> dict:
    """
    Run the Prevention Agent on a completed scan.

    All four detection agents must have already run for this scrape_id
    and stored their results in Redis before calling this endpoint.

    Full test flow:
      1. POST /scrape-test             { url, session_id }
      2. POST /detect-test             { scrape_id, session_id }
      3. POST /pricing-detect-test     { scrape_id, session_id }
      4. POST /behavioral-detect-test  { scrape_id, session_id }
      5. POST /visual-detect-test      { scrape_id, session_id }
      6. POST /prevention-test         { scrape_id, session_id }

    Returns patch_instructions for the browser extension content script.
    """
    from agents.prevention_agent.runner import run_prevention_agent
    try:
        result = await run_prevention_agent(
            scrape_id  = body.scrape_id,
            session_id = body.session_id,
        )
        return result
    except Exception as exc:
        logger.error("prevention_test_error", error=str(exc), exc_info=True)
        return {"error": str(exc)}


# ═════════════════════════════════════════════════════════════
#  MCP TOOLS
# ═════════════════════════════════════════════════════════════

@mcp.tool()
async def scrape_page(url: str, session_id: str) -> str:
    """
    Scrape a URL with Playwright and store the full payload in Redis.

    Args:
        url        : Full URL to scrape (must be http/https)
        session_id : Session ID for cross-page context

    Returns:
        JSON string with scrape_id, page_type, url, and session_id.
    """
    try:
        result = await handle_scrape_page(url=url, session_id=session_id)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("mcp_scrape_page_error", error=str(exc))
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def get_agent_payload(scrape_id: str, agent: str) -> str:
    """
    Retrieve the cached agent input payload for a given scrape.

    Args:
        scrape_id : Scrape ID returned by scrape_page
        agent     : One of "nlp", "pricing", "behavioral", "visual"

    Returns:
        JSON string of the agent's input payload, or {"error": ...} if not found.
    """
    redis = await get_redis_client()
    key_map = {
        "nlp"        : f"dg:nlp-payload:{scrape_id}",
        "pricing"    : f"dg:pricing-payload:{scrape_id}",
        "behavioral" : f"dg:behavioral-payload:{scrape_id}",
        "visual"     : f"dg:visual-payload:{scrape_id}",
    }
    key = key_map.get(agent)
    if not key:
        return json.dumps({"error": f"Unknown agent: {agent}"})
    try:
        raw = await redis.get(key)
        return raw.decode() if raw else json.dumps({"error": "payload not found"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def get_session_history(session_id: str) -> str:
    """
    Return the ordered list of scrape IDs for this session.
    Used by the Orchestrator to decide cross-page routing.

    Args:
        session_id : The session ID

    Returns:
        JSON array of scrape metadata objects.
    """
    redis = await get_redis_client()
    store = SessionStore(redis)
    try:
        scrape_ids = await store.get_session_scrape_ids(session_id)
        metas = []
        for sid in scrape_ids:
            meta = await store.get_scrape_meta(sid)
            if meta:
                metas.append(meta)
        return json.dumps({"session_id": session_id, "scrapes": metas})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def run_nlp_detection(scrape_id: str, session_id: str) -> str:
    """
    Run the NLP Agent on a scraped page.
    Detects: False Urgency (DP01), Confirm Shaming (DP02),
             Disguised Ads (DP03), Trick Question (DP04).

    Args:
        scrape_id  : Scrape ID (must already exist in Redis)
        session_id : Session ID

    Returns:
        JSON string of the AggregatedDetectionResult.
    """
    from agents.nlp_agent.runner import run_nlp_agent
    try:
        result = await run_nlp_agent(
            scrape_id  = scrape_id,
            session_id = session_id,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("mcp_nlp_error", error=str(exc), exc_info=True)
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def run_pricing_detection(scrape_id: str, session_id: str) -> str:
    """
    Run the Pricing Agent on a scraped page.
    Detects: Drip Pricing (DP05), Bait and Switch (DP06).

    Args:
        scrape_id  : Scrape ID of the cart/checkout page
        session_id : Session ID (must include a prior product-page scrape)

    Returns:
        JSON string with patterns, financial_impact, and fee breakdown.
    """
    from agents.pricing_agent.runner import run_pricing_agent
    try:
        result = await run_pricing_agent(
            scrape_id  = scrape_id,
            session_id = session_id,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("mcp_pricing_error", error=str(exc), exc_info=True)
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def run_behavioral_detection(scrape_id: str, session_id: str) -> str:
    """
    Run the Behavioral Agent on a scraped page.
    Detects: Basket Sneaking (DP07), Subscription Trap (DP08),
             Nagging (DP09), SaaS Billing (DP10),
             Rogue/Malicious Content (DP11), Forced Action (DP13).

    Args:
        scrape_id  : Scrape ID (must already exist in Redis)
        session_id : Session ID

    Returns:
        JSON string with patterns and behavioral severity score.
    """
    from agents.behavioral_agent.runner import run_behavioral_agent
    try:
        result = await run_behavioral_agent(
            scrape_id  = scrape_id,
            session_id = session_id,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("mcp_behavioral_error", error=str(exc), exc_info=True)
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def run_visual_detection(scrape_id: str, session_id: str) -> str:
    """
    Run the Visual Agent on a scraped page.
    Detects: Disguised Ads (DP03), Interface Interference (DP12).
    Requires a screenshot to have been stored by the scraper.

    Args:
        scrape_id  : Scrape ID (must already exist in Redis)
        session_id : Session ID

    Returns:
        JSON string with visual pattern detection results.
    """
    from agents.visual_agent.runner import run_visual_agent
    try:
        result = await run_visual_agent(
            scrape_id  = scrape_id,
            session_id = session_id,
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("mcp_visual_error", error=str(exc), exc_info=True)
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def run_prevention(scrape_id: str, session_id: str) -> str:
    """
    Run the Prevention Agent for a completed scan.

    Reads all four agent detection results from Redis (keyed by scrape_id),
    dispatches each detected pattern to its prevention strategy, resolves
    conflicts, and stores a PreventionResult in Redis under
    dg:prevention:{scrape_id}.

    All four detection agents must have run before calling this tool.

    Args:
        scrape_id  : Scrape ID (must already exist in Redis)
        session_id : Session ID for cross-page context

    Returns:
        JSON string of the PreventionResult with patch_instructions.
    """
    from agents.prevention_agent.runner import run_prevention_agent
    try:
        result = await run_prevention_agent(
            scrape_id  = scrape_id,
            session_id = session_id,
        )
        logger.info(
            "prevention_tool_called",
            scrape_id     = scrape_id,
            total_patches = result.get("total_patches", 0),
        )
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("mcp_prevention_error", error=str(exc), exc_info=True)
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def store_detection(
    scrape_id        : str,
    session_id       : str,
    detection_result : dict,
    prevention_result: dict,
) -> str:
    """
    Persist a completed detection + prevention result to Redis.

    Args:
        scrape_id         : Scrape this detection belongs to
        session_id        : Session ID
        detection_result  : Merged dict of all agent results
        prevention_result : PreventionResult dict from Prevention Agent

    Returns:
        JSON confirmation with stored scrape_id.
    """
    redis = await get_redis_client()
    combined = {
        "scrape_id"       : scrape_id,
        "session_id"      : session_id,
        "detection"       : detection_result,
        "prevention"      : prevention_result,
    }
    try:
        await redis.setex(
            f"dg:result:{scrape_id}",
            3600,
            json.dumps(combined, default=str),
        )
        logger.info("detection_stored", scrape_id=scrape_id)
        return json.dumps({"stored": True, "scrape_id": scrape_id})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def fetch_similar_patterns(
    text        : str,
    top_k       : int  = 5,
    pattern_code: str | None = None,
) -> str:
    """
    Find similar previously-detected dark patterns using vector search.
    Used by detection agents to enrich prompts with historical examples.

    NOTE: Full Qdrant implementation in a future phase.
    Currently returns an empty matches list.

    Args:
        text         : Text snippet to search for similar patterns
        top_k        : Number of results to return
        pattern_code : Optional filter e.g. "DP01"

    Returns:
        JSON with a matches list.
    """
    return json.dumps({"matches": [], "note": "Qdrant integration pending"})


# ═════════════════════════════════════════════════════════════
#  MOUNT MCP + RUN
# ═════════════════════════════════════════════════════════════

app.mount("/mcp", mcp.sse_app())


if __name__ == "__main__":
    uvicorn.run(
        "mcp_server.server:app",
        host   = "0.0.0.0",
        port   = settings.mcp_port,
        reload = False,
    )