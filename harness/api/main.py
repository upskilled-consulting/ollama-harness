"""
harness/api/main.py — FastAPI application.

Replaces server.py (Flask). Key improvements:
- Async-native: streaming responses via WebSocket without threading hacks
- Auto OpenAPI docs at /docs
- Lifespan context for clean startup/shutdown
- Dashboard served as a static Vite build (no server-side rendering)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from harness.config import EVAL_OUTPUT, ROOT, ensure_dirs, settings
from harness.api.routes import data, mcp, queue, runs, tasks
from harness.api.ws import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    yield


app = FastAPI(
    title="Harness",
    description="Self-improving agentic research swarm",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:7860"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(runs.router,   prefix="/api")
app.include_router(data.router,   prefix="/api")
app.include_router(queue.router,  prefix="/api")
app.include_router(tasks.router,  prefix="/api")
app.include_router(mcp.router,    prefix="/api/mcp")
app.include_router(ws_router)

# Serve compiled dashboard at root (production)
_dashboard_dist = ROOT / "dashboard" / "dist"
if _dashboard_dist.exists():
    app.mount("/", StaticFiles(directory=str(_dashboard_dist), html=True), name="dashboard")


def serve():
    import uvicorn
    uvicorn.run(
        "harness.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        reload_dirs=[str(ROOT / "harness")],
    )


if __name__ == "__main__":
    serve()
