from contextlib import asynccontextmanager
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )
import uvicorn
from fastapi import FastAPI

from backend.api.v1.health import router as health_router
from backend.api.v1.scan import router as scan_router
from backend.cache.redis_client import close_redis_client, get_redis_client
from backend.scraper.browser_pool import close_browser_pool, init_browser_pool
from config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await get_redis_client()
    await init_browser_pool()
    yield
    # Shutdown
    await close_browser_pool()
    await close_redis_client()


app = FastAPI(
    title="Dark Guard AI",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(scan_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"message": "Dark Guard Backend Running", "version": "0.2.0"}


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.is_development,
    )