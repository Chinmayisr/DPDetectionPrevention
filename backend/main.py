from fastapi import FastAPI

from backend.api.v1.health import router as health_router
from backend.api.v1.scan import router as scan_router

app = FastAPI(
    title="Dark Guard AI",
    version="1.0.0"
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(scan_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "message": "Dark Guard Backend Running"
    }