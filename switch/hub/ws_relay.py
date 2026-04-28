from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .daemon_connection import DaemonConnectionPool

logger = logging.getLogger(__name__)


class WsRelay:
    """
    Browser-facing WebSocket relay.

    Receives messages from browsers, routes them to the correct daemon.
    Receives messages from daemons (via pool callback), routes to subscribed browsers.

    Browser protocol:
      -> { type: "pty.create", daemonId, workDir, tool?, cols?, rows? }
      -> { type: "pty.input", daemonId, sessionId, data }
      -> { type: "pty.resize", daemonId, sessionId, cols, rows }
      -> { type: "session.stop", daemonId, sessionId }
      -> { type: "session.list", daemonId }
      -> { type: "session.subscribe", daemonId, sessionId }

      <- { type: "pty.created", daemonId, session }
      <- { type: "pty.output", daemonId, sessionId, data }
      <- { type: "pty.exit", daemonId, sessionId, code }
      <- { type: "session.input_required", daemonId, sessionId, reason, source }
      <- { type: "session.input_resolved", daemonId, sessionId }
      <- { type: "session.subscribed", daemonId, session }
      <- { type: "session.list", daemonId, sessions }
      <- { type: "error", message }
    """

    def __init__(self, pool: DaemonConnectionPool) -> None:
        self.pool = pool
        self._clients: set[WebSocket] = set()

    async def handle_browser(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        logger.info("Browser connected")
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    req = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send_to_browser(ws, {"type": "error", "message": "Invalid JSON"})
                    continue
                await self._handle_browser_message(ws, req)
        except WebSocketDisconnect:
            logger.info("Browser disconnected")
        finally:
            self._clients.discard(ws)

    async def _handle_browser_message(self, ws: WebSocket, req: dict[str, Any]) -> None:
        daemon_id = req.get("daemonId")
        if not daemon_id:
            await self._send_to_browser(ws, {"type": "error", "message": "Missing daemonId"})
            return

        # Forward to daemon, stripping daemonId (daemon doesn't need it)
        daemon_msg = {k: v for k, v in req.items() if k != "daemonId"}
        try:
            await self.pool.send(daemon_id, daemon_msg)
        except RuntimeError as e:
            await self._send_to_browser(ws, {
                "type": "error",
                "message": str(e),
                "requestType": req.get("type"),
            })

    async def on_daemon_message(self, daemon_id: str, msg: dict[str, Any]) -> None:
        """Called by the connection pool when a daemon sends a message."""
        # Inject daemonId so browser knows which daemon it came from
        msg["daemonId"] = daemon_id
        logger.debug("relay to %d browsers: %s", len(self._clients), msg.get("type", "?"))
        # Broadcast to all connected browsers
        await self._broadcast(msg)

    async def _broadcast(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, default=str)
        disconnected = []
        for ws in self._clients:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self._clients.discard(ws)

    @staticmethod
    async def _send_to_browser(ws: WebSocket, data: dict[str, Any]) -> None:
        try:
            await ws.send_text(json.dumps(data, default=str))
        except Exception:
            pass
