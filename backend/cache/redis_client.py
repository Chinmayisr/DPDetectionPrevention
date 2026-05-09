"""
backend/cache/redis_client.py
─────────────────────────────────────────────────────────────────
Async Redis connection pool singleton.
"""
from __future__ import annotations

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

import structlog
from config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

_pool: ConnectionPool | None = None
_client: Redis | None = None


async def get_redis_client() -> Redis:
    global _pool, _client
    if _client is not None:
        return _client

    _pool = ConnectionPool.from_url(
        settings.redis_url,
        max_connections=20,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    _client = aioredis.Redis(connection_pool=_pool)
    await _client.ping()
    logger.info("redis_connected", url=settings.redis_url)
    return _client


async def close_redis_client() -> None:
    global _pool, _client
    if _client:
        await _client.aclose()
        _client = None
    if _pool:
        await _pool.aclose()
        _pool = None
    logger.info("redis_disconnected")