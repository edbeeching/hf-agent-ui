from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.asyncio.server import Server, ServerConnection

from .pty_session import PtySession
from .session_manager import AnySession, SessionManager

logger = logging.getLogger(__name__)


class DaemonWsServer:
    """
    WebSocket server that accepts connections from the hub.

    Protocol (client = hub, server = daemon):

    Client -> Server:
      { type: "pty.create", workDir, tool?, cols?, rows? }
      { type: "pty.input", sessionId, data }
      { type: "pty.resize", sessionId, cols, rows }
      { type: "session.stop", sessionId }
      { type: "session.remove", sessionId }
      { type: "session.list" }
      { type: "session.subscribe", sessionId }

    Server -> Client:
      { type: "pty.created", session: PtySessionInfo }
      { type: "pty.output", sessionId, data }
      { type: "pty.exit", sessionId, code }
      { type: "session.input_required", sessionId, reason, source }
      { type: "session.input_resolved", sessionId }
      { type: "session.subscribed", session }
      { type: "session.list", sessions: [...] }
      { type: "error", message, requestType? }
    """

    def __init__(self, manager: SessionManager, port: int) -> None:
        self.manager = manager
        self.port = port
        self._server: Server | None = None
        # Track subscriptions: ws -> set of session_ids
        self._subscriptions: dict[ServerConnection, set[str]] = {}

    async def start(self) -> None:
        self._server = await websockets.serve(self._handle_connection, "0.0.0.0", self.port)
        logger.info("Daemon WebSocket server listening on ws://0.0.0.0:%d", self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_connection(self, ws: ServerConnection) -> None:
        self._subscriptions[ws] = set()
        logger.info("Hub connected from %s", ws.remote_address)
        try:
            async for raw in ws:
                try:
                    req = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send(ws, {"type": "error", "message": "Invalid JSON"})
                    continue
                await self._handle_request(ws, req)
        except websockets.ConnectionClosed:
            logger.info("Hub disconnected")
        finally:
            # Clean up subscriptions
            self._unsubscribe_all(ws)
            self._subscriptions.pop(ws, None)

    async def _handle_request(self, ws: ServerConnection, req: dict[str, Any]) -> None:
        msg_type = req.get("type", "")

        match msg_type:
            case "pty.create":
                tool = req.get("tool", "claude")
                work_dir = req.get("workDir", ".")
                cols = req.get("cols", 120)
                rows = req.get("rows", 40)
                session = self.manager.create_pty(work_dir, tool, cols, rows)
                self._subscribe_any(ws, session)
                await session.start()
                await self._send(ws, {
                    "type": "pty.created",
                    "session": json.loads(
                        json.dumps(session.to_info().__dict__, default=str)
                    ),
                })

            case "pty.input":
                session = self.manager.get(req.get("sessionId", ""))
                if not session or not isinstance(session, PtySession):
                    await self._send(ws, {
                        "type": "error",
                        "message": f"PTY session not found: {req.get('sessionId')}",
                        "requestType": msg_type,
                    })
                    return
                session.write(req.get("data", ""))

            case "pty.resize":
                session = self.manager.get(req.get("sessionId", ""))
                if not session or not isinstance(session, PtySession):
                    return
                session.resize(req.get("cols", 120), req.get("rows", 40))

            case "session.subscribe":
                session = self.manager.get(req.get("sessionId", ""))
                if not session:
                    await self._send(ws, {
                        "type": "error",
                        "message": f"Session not found: {req.get('sessionId')}",
                        "requestType": msg_type,
                    })
                    return
                self._subscribe_any(ws, session)
                payload: dict[str, Any] = {
                    "type": "session.subscribed",
                    "session": json.loads(json.dumps(session.to_info().__dict__, default=str)),
                }
                await self._send(ws, payload)
                if isinstance(session, PtySession):
                    for chunk in session.get_output_buffer():
                        await self._send(ws, {
                            "type": "pty.output",
                            "sessionId": session.id,
                            "data": chunk,
                        })

            case "session.stop":
                if not self.manager.stop(req.get("sessionId", "")):
                    await self._send(ws, {
                        "type": "error",
                        "message": f"Session not found: {req.get('sessionId')}",
                        "requestType": msg_type,
                    })

            case "session.remove":
                if not self.manager.remove(req.get("sessionId", "")):
                    await self._send(ws, {
                        "type": "error",
                        "message": f"Session not found: {req.get('sessionId')}",
                        "requestType": msg_type,
                    })

            case "session.list":
                await self._send(ws, {
                    "type": "session.list",
                    "sessions": self.manager.list(),
                })

            case _:
                await self._send(ws, {
                    "type": "error",
                    "message": f"Unknown request type: {msg_type}",
                })

    def _subscribe_any(self, ws: ServerConnection, session: AnySession) -> None:
        subs = self._subscriptions.get(ws)
        if subs is None or session.id in subs:
            return
        subs.add(session.id)

        async def on_event(event: dict[str, Any]) -> None:
            try:
                logger.debug("forwarding %s to hub", event.get("type", "?"))
                await self._send(ws, event)
            except Exception:
                logger.exception("Failed to forward event to hub")

        session.on_event(on_event)
        # Store callback ref for cleanup
        if not hasattr(ws, "_session_callbacks"):
            ws._session_callbacks = {}  # type: ignore[attr-defined]
        ws._session_callbacks[session.id] = on_event  # type: ignore[attr-defined]

    def _unsubscribe_all(self, ws: ServerConnection) -> None:
        callbacks = getattr(ws, "_session_callbacks", {})
        for session_id, cb in callbacks.items():
            session = self.manager.get(session_id)
            if session:
                session.remove_callback(cb)

    @staticmethod
    async def _send(ws: ServerConnection, data: dict[str, Any]) -> None:
        try:
            await ws.send(json.dumps(data, default=str))
        except websockets.ConnectionClosed:
            pass
