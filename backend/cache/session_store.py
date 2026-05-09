"""
backend/cache/session_store.py
─────────────────────────────────────────────────────────────────
Session-aware Redis storage for scrape results.

Key scheme (all keys prefixed with "dg:" for Dark Guard):
  dg:session:{session_id}:meta          → ScrapeSession JSON
  dg:session:{session_id}:scrape_ids    → Redis list of scrape IDs (ordered)
  dg:scrape:{scrape_id}:meta            → lightweight metadata (URL, type, ts)
  dg:scrape:{scrape_id}:dom             → full structured DOM payload (no screenshot)
  dg:scrape:{scrape_id}:screenshot      → base64 JPEG (shorter TTL)
  dg:scrape:{scrape_id}:lock            → distributed lock
  dg:nlp:{scrape_id}                    → NLPAgentPayload JSON
  dg:visual:{scrape_id}                 → VisualAgentPayload JSON
  dg:pricing:{session_id}:{scrape_id}   → PricingAgentPayload JSON
  dg:behavioral:{session_id}:{scrape_id}→ BehavioralAgentPayload JSON
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from redis.asyncio import Redis

from backend.scraper.models import (
    BehavioralAgentPayload,
    NLPAgentPayload,
    PageType,
    PricingAgentPayload,
    ScrapedPage,
    ScrapeSession,
    VisualAgentPayload,
)
from backend.scraper.playwright_scraper import (
    build_behavioral_payload,
    build_nlp_payload,
    build_pricing_payload,
    build_visual_payload,
)
from config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

_SESSION_TTL   = 1800   # 30 minutes of inactivity
_DOM_TTL       = 600    # 10 minutes
_SCREENSHOT_TTL = 120   # 2 minutes
_AGENT_TTL     = 600    # 10 minutes
_LOCK_TTL      = 60     # 1 minute max lock


# ── Key builders ──────────────────────────────────────────────

def _session_meta_key(session_id: str) -> str:
    return f"dg:session:{session_id}:meta"

def _session_scrape_ids_key(session_id: str) -> str:
    return f"dg:session:{session_id}:scrape_ids"

def _scrape_meta_key(scrape_id: str) -> str:
    return f"dg:scrape:{scrape_id}:meta"

def _scrape_dom_key(scrape_id: str) -> str:
    return f"dg:scrape:{scrape_id}:dom"

def _scrape_screenshot_key(scrape_id: str) -> str:
    return f"dg:scrape:{scrape_id}:screenshot"

def _scrape_lock_key(scrape_id: str) -> str:
    return f"dg:scrape:{scrape_id}:lock"

def _nlp_key(scrape_id: str) -> str:
    return f"dg:nlp:{scrape_id}"

def _visual_key(scrape_id: str) -> str:
    return f"dg:visual:{scrape_id}"

def _pricing_key(session_id: str, scrape_id: str) -> str:
    return f"dg:pricing:{session_id}:{scrape_id}"

def _behavioral_key(session_id: str, scrape_id: str) -> str:
    return f"dg:behavioral:{session_id}:{scrape_id}"


# ═══════════════════════════════════════════════════════════════
#  SESSION STORE CLASS
# ═══════════════════════════════════════════════════════════════

class SessionStore:
    """
    All Redis read/write operations for session-scoped scrape data.

    Usage:
        store = SessionStore(redis_client)
        await store.save_scrape(scraped_page)
        payload = await store.get_nlp_payload(scrape_id)
    """

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    # ── Session management ────────────────────────────────────

    async def get_or_create_session(self, session_id: str) -> ScrapeSession:
        """Return existing session or create a fresh one."""
        raw = await self._r.get(_session_meta_key(session_id))
        if raw:
            data = json.loads(raw)
            return ScrapeSession(**data)
        session = ScrapeSession(session_id=session_id)
        await self._save_session(session)
        return session

    async def _save_session(self, session: ScrapeSession) -> None:
        session.updated_at = datetime.now(timezone.utc)
        await self._r.setex(
            _session_meta_key(session.session_id),
            _SESSION_TTL,
            session.model_dump_json(),
        )
        # Reset TTL on the scrape_ids list too
        await self._r.expire(
            _session_scrape_ids_key(session.session_id),
            _SESSION_TTL,
        )

    # ── Distributed lock ──────────────────────────────────────

    async def acquire_lock(self, scrape_id: str) -> bool:
        """Acquire a lock for `scrape_id`. Returns True if acquired."""
        acquired = await self._r.set(
            _scrape_lock_key(scrape_id), "1", nx=True, ex=_LOCK_TTL
        )
        return bool(acquired)

    async def release_lock(self, scrape_id: str) -> None:
        await self._r.delete(_scrape_lock_key(scrape_id))

    # ── Save scraped page ─────────────────────────────────────

    async def save_scrape(self, page: ScrapedPage) -> None:
        """
        Persist all data for a scraped page in a Redis pipeline.
        Also builds and stores all four agent payloads.
        """
        scrape_id = page.scrape_id
        session_id = page.session_id

        # Retrieve or create session
        session = await self.get_or_create_session(session_id)

        # Get the previous scrape for comparison agents
        previous_page = await self._get_last_dom_for_session(session)

        # Build agent payloads
        nlp_payload      = build_nlp_payload(page)
        visual_payload   = build_visual_payload(page)
        pricing_payload  = build_pricing_payload(page, previous_page)
        behavioral_payload = build_behavioral_payload(page, previous_page)

        # Serialize DOM payload without the large screenshot
        dom_data = page.model_dump()
        screenshot_b64 = dom_data.pop("screenshot_b64", None)

        # Write everything in a single pipeline (one round-trip)
        pipe = self._r.pipeline(transaction=False)

        # 1. Scrape metadata (lightweight)
        meta = {
            "scrape_id": scrape_id,
            "session_id": session_id,
            "url": page.url,
            "final_url": page.final_url,
            "page_type": page.page_type.value,
            "title": page.title,
            "scraped_at": page.scraped_at.isoformat(),
            "scrape_duration_ms": page.scrape_duration_ms,
            "button_count": len(page.buttons),
            "overlay_count": len(page.overlays),
            "price_count": len(page.prices),
            "auto_popup_count": page.auto_popup_count,
        }
        pipe.setex(_scrape_meta_key(scrape_id), _DOM_TTL, json.dumps(meta))

        # 2. Full DOM payload (no screenshot)
        pipe.setex(_scrape_dom_key(scrape_id), _DOM_TTL, json.dumps(dom_data, default=str))

        # 3. Screenshot (short TTL, large value)
        if screenshot_b64:
            pipe.setex(
                _scrape_screenshot_key(scrape_id),
                _SCREENSHOT_TTL,
                screenshot_b64,
            )

        # 4. Agent payloads
        pipe.setex(
            _nlp_key(scrape_id),
            _AGENT_TTL,
            nlp_payload.model_dump_json(),
        )
        pipe.setex(
            _visual_key(scrape_id),
            _AGENT_TTL,
            visual_payload.model_dump_json(),
        )
        pipe.setex(
            _pricing_key(session_id, scrape_id),
            _AGENT_TTL,
            pricing_payload.model_dump_json(),
        )
        pipe.setex(
            _behavioral_key(session_id, scrape_id),
            _AGENT_TTL,
            behavioral_payload.model_dump_json(),
        )

        # 5. Append scrape_id to session's ordered list
        pipe.rpush(_session_scrape_ids_key(session_id), scrape_id)
        pipe.expire(_session_scrape_ids_key(session_id), _SESSION_TTL)

        await pipe.execute()

        # Update session metadata (outside pipeline to use fresh data)
        session.scrape_ids.append(scrape_id)
        session.page_types.append(page.page_type)
        session.urls.append(page.url)
        await self._save_session(session)

        logger.info(
            "scrape_saved_to_redis",
            scrape_id=scrape_id,
            session_id=session_id,
            page_type=page.page_type.value,
            keys_written=7,
        )

    # ── Retrieve payloads ─────────────────────────────────────

    async def get_nlp_payload(self, scrape_id: str) -> NLPAgentPayload | None:
        raw = await self._r.get(_nlp_key(scrape_id))
        if not raw:
            return None
        return NLPAgentPayload.model_validate_json(raw)

    async def get_visual_payload(self, scrape_id: str) -> VisualAgentPayload | None:
        raw = await self._r.get(_visual_key(scrape_id))
        if not raw:
            return None
        return VisualAgentPayload.model_validate_json(raw)

    async def get_pricing_payload(
        self, session_id: str, scrape_id: str
    ) -> PricingAgentPayload | None:
        raw = await self._r.get(_pricing_key(session_id, scrape_id))
        if not raw:
            return None
        return PricingAgentPayload.model_validate_json(raw)

    async def get_behavioral_payload(
        self, session_id: str, scrape_id: str
    ) -> BehavioralAgentPayload | None:
        raw = await self._r.get(_behavioral_key(session_id, scrape_id))
        if not raw:
            return None
        return BehavioralAgentPayload.model_validate_json(raw)

    async def get_screenshot(self, scrape_id: str) -> str | None:
        """Return base64 JPEG string or None if expired."""
        return await self._r.get(_scrape_screenshot_key(scrape_id))

    async def get_scrape_meta(self, scrape_id: str) -> dict | None:
        raw = await self._r.get(_scrape_meta_key(scrape_id))
        return json.loads(raw) if raw else None

    async def get_scrape_dom(self, scrape_id: str) -> dict | None:
        raw = await self._r.get(_scrape_dom_key(scrape_id))
        return json.loads(raw) if raw else None

    async def get_session_scrape_ids(self, session_id: str) -> list[str]:
        """Return ordered list of scrape IDs for a session."""
        ids = await self._r.lrange(_session_scrape_ids_key(session_id), 0, -1)
        return ids or []

    async def get_last_two_scrapes(
        self, session_id: str
    ) -> tuple[dict | None, dict | None]:
        """
        Return (previous, current) DOM payloads for a session.
        Returns (None, current) if only one scrape exists.
        Returns (None, None) if session has no scrapes.
        """
        ids = await self.get_session_scrape_ids(session_id)
        if not ids:
            return None, None
        current = await self.get_scrape_dom(ids[-1]) if len(ids) >= 1 else None
        previous = await self.get_scrape_dom(ids[-2]) if len(ids) >= 2 else None
        return previous, current

    # ── Private helpers ───────────────────────────────────────

    async def _get_last_dom_for_session(
        self, session: ScrapeSession
    ) -> ScrapedPage | None:
        """
        Return the most recently scraped page as a ScrapedPage object.
        Used internally to build comparison payloads.
        """
        if not session.scrape_ids:
            return None
        last_id = session.scrape_ids[-1]
        dom_data = await self.get_scrape_dom(last_id)
        if not dom_data:
            return None
        try:
            return ScrapedPage(**dom_data)
        except Exception as exc:
            logger.warning("session_dom_parse_error", scrape_id=last_id, error=str(exc))
            return None

    async def ping(self) -> bool:
        try:
            return await self._r.ping()
        except Exception:
            return False