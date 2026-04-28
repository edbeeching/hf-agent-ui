from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from .daemon_connection import DaemonConnectionPool
from .daemon_registry import DaemonRegistry
from .routes import router
from .ws_relay import WsRelay

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = DaemonRegistry()
    pool = DaemonConnectionPool(on_message=lambda did, msg: _on_daemon_message(app, did, msg))
    relay = WsRelay(pool)

    app.state.registry = registry
    app.state.pool = pool
    app.state.relay = relay

    await registry.start_prune_loop()
    logger.info("Hub started")

    yield

    await pool.disconnect_all()
    registry.stop()
    logger.info("Hub stopped")


async def _on_daemon_message(app: FastAPI, daemon_id: str, msg: dict) -> None:
    relay: WsRelay = app.state.relay
    await relay.on_daemon_message(daemon_id, msg)


app = FastAPI(title="Switch Hub", lifespan=lifespan)

app.include_router(router)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    relay: WsRelay = app.state.relay
    await relay.handle_browser(ws)


# Serve static web UI if it exists
STATIC_DIR = Path(__file__).parent.parent.parent / "web" / "dist"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
