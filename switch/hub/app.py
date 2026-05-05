from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, WebSocket, status
from fastapi.staticfiles import StaticFiles

from .daemon_connection import DaemonConnectionPool
from .daemon_registry import DaemonRegistry
from .routes import router
from .security import is_browser_ws_authorized
from .ws_relay import WsRelay

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = DaemonRegistry()
    pool = DaemonConnectionPool(registry, on_message=lambda did, msg: _on_daemon_message(app, did, msg))
    relay = WsRelay(pool)

    app.state.registry = registry
    app.state.pool = pool
    app.state.relay = relay

    logger.info("Hub started")

    yield

    await pool.disconnect_all()
    registry.stop()
    logger.info("Hub stopped")


async def _on_daemon_message(app: FastAPI, daemon_id: str, msg: dict) -> None:
    relay: WsRelay = app.state.relay
    await relay.on_daemon_message(daemon_id, msg)


app = FastAPI(title="agentic-ui Hub", lifespan=lifespan)

app.include_router(router)


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response: Response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'"
    ))
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if not is_browser_ws_authorized(ws):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    relay: WsRelay = app.state.relay
    await relay.handle_browser(ws)


@app.websocket("/daemon/ws")
async def daemon_ws_endpoint(ws: WebSocket) -> None:
    pool: DaemonConnectionPool = app.state.pool
    await pool.handle_daemon(ws, expected_token=os.environ.get("SWITCH_DAEMON_TOKEN"))


# Serve bundled web UI (skipped in dev mode — use Vite dev server instead)
if not os.environ.get("SWITCH_DEV"):
    STATIC_DIR = Path(__file__).parent / "static"
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
