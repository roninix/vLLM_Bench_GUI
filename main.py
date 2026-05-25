"""Entry point — starts uvicorn on port 7842."""

import asyncio
import sys
from pathlib import Path

import uvicorn

# Ensure project root is on sys.path
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import init_db, setting_get
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware


async def _vendor_setup():
    """Auto-download CDN vendor assets on first run."""
    vendor_dir = ROOT / "static" / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)

    assets = {
        "alpine.min.js": "https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js",
        "chart.min.js": "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",
        "chartjs-plugin-annotation.min.js": "https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0/dist/chartjs-plugin-annotation.min.js",
    }

    import aiohttp
    async with aiohttp.ClientSession() as session:
        for filename, url in assets.items():
            dest = vendor_dir / filename
            if dest.exists() and dest.stat().st_size > 100:
                continue  # Already downloaded
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        dest.write_bytes(content)
                        print(f"  ✓ Downloaded {filename}")
                    else:
                        print(f"  ✗ Failed to download {filename} (HTTP {resp.status})")
            except Exception as e:
                print(f"  ✗ Failed to download {filename}: {e}")


class DBMiddleware(BaseHTTPMiddleware):
    """Attach a fresh DB connection to each request."""

    async def dispatch(self, request: Request, call_next):
        request.state.db = await init_db()
        try:
            response = await call_next(request)
            return response
        finally:
            try:
                await request.state.db.close()
            except Exception:
                pass


def create_app():
    """Factory — builds FastAPI app with routes and DB middleware."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await _vendor_setup()
        yield

    app = FastAPI(title="vLLM Benchmark GUI", lifespan=lifespan)
    app.add_middleware(DBMiddleware)

    # Serve static files
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(str(ROOT / "static" / "index.html"))

    # Import and include routers
    from api.routes_servers import router as servers_router
    from api.routes_benchmark import router as benchmark_router
    from api.routes_results import router as results_router
    from api.routes_backup import router as backup_router

    app.include_router(servers_router)
    app.include_router(benchmark_router)
    app.include_router(results_router)
    app.include_router(backup_router)

    return app


def main():
    """Entry point — resolves port from settings or defaults to 7842."""
    port = 7842
    try:
        db = asyncio.run(init_db())
        stored = asyncio.run(setting_get(db, "app_port"))
        asyncio.run(db.close())
        if stored:
            port = int(stored)
    except Exception:
        pass

    app = create_app()
    print(f"\n  ◈ vLLM Benchmark GUI → http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
