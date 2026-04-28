from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import websockets
from websockets.asyncio.client import ClientConnection

from .daemon_registry import DaemonInfo

logger = logging.getLogger(__name__)

MessageCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class DaemonConnection:
    """Manages a WebSocket connection to a single daemon."""

    def __init__(self, daemon: DaemonInfo, on_message: MessageCallback) -> None:
        self.daemon = daemon
        self._on_message = on_message
        self._ws: ClientConnection | None = None
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def connect(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._connect_loop())

    async def _connect_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                uri = f"ws://{self.daemon.host}:{self.daemon.port}"
                # The daemon host might be 0.0.0.0 — use hostname or localhost
                if self.daemon.host == "0.0.0.0":
                    uri = f"ws://{self.daemon.hostname}:{self.daemon.port}"

                logger.info("Connecting to daemon %s at %s", self.daemon.name, uri)
                async with websockets.connect(uri) as ws:
                    self._ws = ws
                    backoff = 1.0
                    logger.info("Connected to daemon %s", self.daemon.name)
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            logger.debug("from daemon %s: %s", self.daemon.name, msg.get("type", "?"))
                            await self._on_message(self.daemon.id, msg)
                        except json.JSONDecodeError:
                            logger.warning("Invalid JSON from daemon %s", self.daemon.name)
            except websockets.ConnectionClosed:
                logger.warning("Connection to daemon %s closed", self.daemon.name)
            except Exception:
                logger.warning("Failed to connect to daemon %s, retrying in %.0fs", self.daemon.name, backoff)
            finally:
                self._ws = None

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def send(self, data: dict[str, Any]) -> None:
        if self._ws:
            await self._ws.send(json.dumps(data, default=str))
        else:
            raise RuntimeError(f"Not connected to daemon {self.daemon.name}")

    async def disconnect(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._ws = None
        self._task = None


class DaemonConnectionPool:
    """Manages connections to all registered daemons."""

    def __init__(self, on_message: MessageCallback) -> None:
        self._connections: dict[str, DaemonConnection] = {}
        self._on_message = on_message

    async def connect(self, daemon: DaemonInfo) -> None:
        # Disconnect old connection if it exists (e.g. daemon re-registered)
        old = self._connections.get(daemon.id)
        if old:
            await old.disconnect()
        conn = DaemonConnection(daemon, self._on_message)
        self._connections[daemon.id] = conn
        await conn.connect()

    async def disconnect(self, daemon_id: str) -> None:
        conn = self._connections.pop(daemon_id, None)
        if conn:
            await conn.disconnect()

    async def send(self, daemon_id: str, data: dict[str, Any]) -> None:
        conn = self._connections.get(daemon_id)
        if not conn:
            raise RuntimeError(f"No connection to daemon {daemon_id}")
        await conn.send(data)

    def is_connected(self, daemon_id: str) -> bool:
        conn = self._connections.get(daemon_id)
        return conn.connected if conn else False

    async def disconnect_all(self) -> None:
        for conn in self._connections.values():
            await conn.disconnect()
        self._connections.clear()
