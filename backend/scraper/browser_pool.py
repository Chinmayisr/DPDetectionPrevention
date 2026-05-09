"""
backend/scraper/browser_pool.py
─────────────────────────────────────────────────────────────────
Persistent async browser context pool.

Maintains N pre-warmed Playwright browser contexts in an asyncio.Queue.
Requests check out a context, use it, then return it.
A health-check on return replaces crashed contexts automatically.

Lifecycle:
    await BrowserPool.create(size=5)  → call at app startup
    async with pool.acquire() as ctx  → use in scraper
    await pool.close()                → call at app shutdown
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    async_playwright,
)

from config import get_settings

settings = get_settings()


# Realistic Chrome user-agent pool — rotate per context to avoid fingerprinting
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def _make_context_options(index: int) -> dict:
    """Return browser context creation kwargs for context slot `index`."""
    ua = _USER_AGENTS[index % len(_USER_AGENTS)]
    return {
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": ua,
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "geolocation": {"longitude": -74.006, "latitude": 40.7128},
        "permissions": [],            # deny all permissions by default
        "java_script_enabled": True,
        "accept_downloads": False,
        "bypass_csp": True,           # allow our evaluation scripts on strict-CSP pages
        "color_scheme": "light",
        "extra_http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
        },
    }


class BrowserPool:
    """
    Thread-safe async pool of Playwright BrowserContext objects.
    Use as an application-level singleton.
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._pool: asyncio.Queue[tuple[int, BrowserContext]] = asyncio.Queue()
        self._size: int = 0
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls, size: int | None = None) -> "BrowserPool":
        """
        Instantiate and warm the pool.
        Called once at application startup.
        """
        pool = cls()
        pool._size = size or settings.playwright_pool_size
        await pool._start()
        return pool

    async def _start(self) -> None:
        self._playwright = await async_playwright().start()

        launch_kwargs: dict = {
            "headless": settings.playwright_headless,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",  # hides webdriver flag
                "--disable-infobars",
                "--window-size=1920,1080",
                "--disable-extensions",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        }

        self._browser = await getattr(
            self._playwright, settings.playwright_browser
        ).launch(**launch_kwargs)

        for i in range(self._size):
            ctx = await self._create_context(i)
            await self._pool.put((i, ctx))

    async def _create_context(self, index: int) -> BrowserContext:
        """Create a single fresh browser context."""
        assert self._browser is not None
        ctx = await self._browser.new_context(**_make_context_options(index))

        # Inject stealth script — removes webdriver navigator property
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        return ctx

    @asynccontextmanager
    async def acquire(
        self, timeout: float = 30.0
    ) -> AsyncIterator[BrowserContext]:
        """
        Context manager that checks out a BrowserContext from the pool.

        Usage:
            async with pool.acquire() as ctx:
                page = await ctx.new_page()
                ...
        """
        try:
            index, ctx = await asyncio.wait_for(
                self._pool.get(), timeout=timeout
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                "BrowserPool exhausted — all contexts busy. "
                "Increase PLAYWRIGHT_POOL_SIZE or retry."
            )

        healthy = True
        try:
            yield ctx
        except Exception:
            # Context may be in a bad state — mark for replacement
            healthy = False
            raise
        finally:
            if healthy:
                # Close all pages in the context before returning it to pool
                for page in ctx.pages:
                    try:
                        await page.close()
                    except Exception:
                        pass
                await self._pool.put((index, ctx))
            else:
                # Replace the broken context
                try:
                    await ctx.close()
                except Exception:
                    pass
                new_ctx = await self._create_context(index)
                await self._pool.put((index, new_ctx))

    async def close(self) -> None:
        """Close all contexts and the browser. Call at shutdown."""
        while not self._pool.empty():
            try:
                _, ctx = self._pool.get_nowait()
                await ctx.close()
            except Exception:
                pass
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()


# ── Module-level singleton ────────────────────────────────────
# Initialised by calling init_browser_pool() at app startup

_pool_instance: BrowserPool | None = None


async def init_browser_pool() -> BrowserPool:
    global _pool_instance
    _pool_instance = await BrowserPool.create()
    return _pool_instance


async def close_browser_pool() -> None:
    global _pool_instance
    if _pool_instance:
        await _pool_instance.close()
        _pool_instance = None


def get_browser_pool() -> BrowserPool:
    if _pool_instance is None:
        raise RuntimeError(
            "BrowserPool not initialised. Call init_browser_pool() at startup."
        )
    return _pool_instance