from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
import uvicorn

app = FastAPI()

mcp = FastMCP("dark-guard-mcp")


@app.get("/")
async def root():
    return {
        "message": "MCP Server Running"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }


@mcp.tool()
async def health_check() -> str:
    return "MCP Server Running"


@mcp.tool()
async def echo(message: str) -> str:
    return f"Echo: {message}"


# Mount MCP routes
app.mount("/mcp", mcp.sse_app())


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001
    )