from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

import websockets
from websockets.asyncio.server import Server, ServerConnection

from .pty_session import PtySession
from .session_assets import SessionImageError, save_session_image
from .session_manager import AnySession, SessionManager
from .worktrees import list_existing_worktrees

logger = logging.getLogger(__name__)
MAX_WS_MESSAGE_BYTES = 12 * 1024 * 1024


class DaemonWsServer:
    """
    WebSocket server that accepts connections from the hub.

    Protocol (client = hub, server = daemon):

    Client -> Server:
      { type: "pty.create", workDir, tool?, cols?, rows?, launchMode?, launchCommand?, launchLabel?, yoloMode?, worktree? }
      { type: "pty.input", sessionId, data, requestId? }
      { type: "pty.resize", sessionId, cols, rows }
      { type: "session.image.send", sessionId, filename, mimeType, dataBase64, prompt }
      { type: "session.stop", sessionId }
      { type: "session.pause", sessionId }
      { type: "session.resume", sessionId }
      { type: "session.rename", sessionId, label? }
      { type: "session.mark_seen", sessionId }
      { type: "app.pause" }
      { type: "app.resume" }
      { type: "session.remove", sessionId }
      { type: "session.list" }
      { type: "session.subscribe", sessionId }
      { type: "worktrees.list", sourceDir, requestId? }

    Server -> Client:
      { type: "pty.created", session: PtySessionInfo }
      { type: "pty.input_ack", sessionId, requestId? }
      { type: "pty.output", sessionId, data }
      { type: "pty.exit", sessionId, code }
      { type: "session.image.sent", sessionId, path, mimeType, size, session }
      { type: "session.input_required", sessionId, reason, source, kind?, title?, message?, detectedAt? }
      { type: "session.input_resolved", sessionId }
      { type: "session.subscribed", session }
      { type: "session.renamed", sessionId, session }
      { type: "session.updated", sessionId, session }
      { type: "session.list", sessions: [...] }
      { type: "worktrees.list", sourceDir, requestId?, worktrees: [...] }
      { type: "error", message, requestType? }
    """

    def __init__(self, manager: SessionManager, port: int) -> None:
        self.manager = manager
        self.port = port
        self._server: Server | None = None
        # Track subscriptions: ws -> set of session_ids
        self._subscriptions: dict[ServerConnection, set[str]] = {}
        self._session_callbacks: dict[Any, dict[str, Any]] = {}

    async def start(self) -> None:
        self._server = await websockets.serve(
            self._handle_connection,
            "0.0.0.0",
            self.port,
            max_size=MAX_WS_MESSAGE_BYTES,
        )
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
            case "worktrees.list":
                source_dir = req.get("sourceDir", ".")
                if not isinstance(source_dir, str):
                    source_dir = "."
                request_id = req.get("requestId")
                if not isinstance(request_id, str):
                    request_id = None
                try:
                    response = {
                        "type": "worktrees.list",
                        "sourceDir": source_dir,
                        "worktrees": [asdict(item) for item in list_existing_worktrees(source_dir)],
                    }
                    if request_id:
                        response["requestId"] = request_id
                    await self._send(ws, response)
                except Exception as exc:
                    response = {
                        "type": "error",
                        "message": str(exc),
                        "requestType": msg_type,
                        "sourceDir": source_dir,
                    }
                    if request_id:
                        response["requestId"] = request_id
                    await self._send(ws, response)

            case "pty.create":
                tool = req.get("tool", "codex")
                work_dir = req.get("workDir", ".")
                cols = req.get("cols", 120)
                rows = req.get("rows", 40)
                session: PtySession | None = None
                try:
                    worktree = req.get("worktree")
                    if worktree is not None and not isinstance(worktree, dict):
                        raise ValueError("worktree must be an object")
                    session = self.manager.create_pty(
                        work_dir,
                        tool,
                        cols,
                        rows,
                        launch_mode=req.get("launchMode", "local"),
                        launch_command=req.get("launchCommand"),
                        launch_label=req.get("launchLabel"),
                        yolo_mode=req.get("yoloMode") is True,
                        worktree=worktree,
                        label=req.get("label") if isinstance(req.get("label"), str) else None,
                    )
                    self._subscribe_any(ws, session)
                    await session.start()
                    await self._send(ws, {
                        "type": "pty.created",
                        "session": _session_payload(session),
                    })
                except Exception as exc:
                    if session:
                        self.manager.discard_failed_create(session.id)
                    await self._send(ws, {
                        "type": "error",
                        "message": str(exc),
                        "requestType": msg_type,
                    })

            case "pty.input":
                session_id = req.get("sessionId", "")
                if not isinstance(session_id, str):
                    session_id = ""
                request_id = req.get("requestId")
                if not isinstance(request_id, str):
                    request_id = None
                session = self.manager.get(session_id)
                if not session or not isinstance(session, PtySession):
                    response = {
                        "type": "error",
                        "message": f"PTY session not found: {session_id or req.get('sessionId')}",
                        "requestType": msg_type,
                        "sessionId": session_id,
                    }
                    if request_id:
                        response["requestId"] = request_id
                    await self._send(ws, response)
                    return
                data = req.get("data", "")
                if not isinstance(data, str):
                    data = ""
                try:
                    if not session.write(data):
                        raise RuntimeError(f"PTY session is not running: {session.id}")
                except (OSError, RuntimeError) as exc:
                    response = {
                        "type": "error",
                        "message": str(exc),
                        "requestType": msg_type,
                        "sessionId": session.id,
                    }
                    if request_id:
                        response["requestId"] = request_id
                    await self._send(ws, response)
                    return
                response = {
                    "type": "pty.input_ack",
                    "sessionId": session.id,
                }
                if request_id:
                    response["requestId"] = request_id
                await self._send(ws, response)

            case "pty.resize":
                session = self.manager.get(req.get("sessionId", ""))
                if not session or not isinstance(session, PtySession):
                    return
                session.resize(req.get("cols", 120), req.get("rows", 40))

            case "session.image.send":
                session = self.manager.get(req.get("sessionId", ""))
                if not session or not isinstance(session, PtySession):
                    await self._send(ws, {
                        "type": "error",
                        "message": f"PTY session not found: {req.get('sessionId')}",
                        "requestType": msg_type,
                    })
                    return
                if session.tool != "codex":
                    await self._send(ws, {
                        "type": "error",
                        "message": "Screenshot paste is currently supported for Codex sessions only",
                        "requestType": msg_type,
                        "sessionId": session.id,
                    })
                    return
                try:
                    image = save_session_image(
                        session_id=session.id,
                        filename=req.get("filename"),
                        mime_type=req.get("mimeType"),
                        data_base64=req.get("dataBase64"),
                    )
                    prompt = req.get("prompt", "")
                    await session.send_image_to_codex(
                        image_path=image.path,
                        prompt=prompt if isinstance(prompt, str) else "",
                    )
                    await self._send(ws, {
                        "type": "session.image.sent",
                        "sessionId": session.id,
                        "path": str(image.path),
                        "mimeType": image.mime_type,
                        "size": image.size,
                        "session": _session_payload(session),
                    })
                except (SessionImageError, ValueError) as exc:
                    await self._send(ws, {
                        "type": "error",
                        "message": str(exc),
                        "requestType": msg_type,
                        "sessionId": session.id,
                    })

            case "session.subscribe":
                session = self.manager.get(req.get("sessionId", ""))
                if not session:
                    await self._send(ws, {
                        "type": "error",
                        "message": f"Session not found: {req.get('sessionId')}",
                        "requestType": msg_type,
                    })
                    return
                self.manager.mark_seen(session.id)
                self._subscribe_any(ws, session)
                payload: dict[str, Any] = {
                    "type": "session.subscribed",
                    "session": _session_payload(session),
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

            case "session.pause":
                session_id = req.get("sessionId", "")
                if not self.manager.pause(session_id):
                    await self._send(ws, {
                        "type": "error",
                        "message": f"Session not found: {session_id}",
                        "requestType": msg_type,
                    })
                    return
                session = self.manager.get(session_id)
                await self._send(ws, {
                    "type": "session.paused",
                    "sessionId": session_id,
                    "session": _session_payload(session),
                })

            case "session.resume":
                session_id = req.get("sessionId", "")
                try:
                    resumed = await self.manager.resume(session_id)
                except Exception as exc:
                    await self._send(ws, {
                        "type": "error",
                        "message": str(exc),
                        "requestType": msg_type,
                        "sessionId": session_id,
                    })
                    return
                if not resumed:
                    await self._send(ws, {
                        "type": "error",
                        "message": f"Session not found: {session_id}",
                        "requestType": msg_type,
                    })
                    return
                session = self.manager.get(session_id)
                if session:
                    self._subscribe_any(ws, session)
                    await self._send(ws, {
                        "type": "session.resumed",
                        "sessionId": session_id,
                        "session": _session_payload(session),
                    })

            case "session.rename":
                session_id = req.get("sessionId", "")
                label = req.get("label")
                if label is not None and not isinstance(label, str):
                    await self._send(ws, {
                        "type": "error",
                        "message": "Session label must be a string",
                        "requestType": msg_type,
                    })
                    return
                if not self.manager.rename(session_id, label):
                    await self._send(ws, {
                        "type": "error",
                        "message": f"Session not found: {session_id}",
                        "requestType": msg_type,
                    })
                    return
                session = self.manager.get(session_id)
                await self._send(ws, {
                    "type": "session.renamed",
                    "sessionId": session_id,
                    "session": _session_payload(session),
                })

            case "session.mark_seen":
                session_id = req.get("sessionId", "")
                if not self.manager.mark_seen(session_id):
                    await self._send(ws, {
                        "type": "error",
                        "message": f"Session not found: {session_id}",
                        "requestType": msg_type,
                    })
                    return
                session = self.manager.get(session_id)
                await self._send(ws, {
                    "type": "session.updated",
                    "sessionId": session_id,
                    "session": _session_payload(session),
                })

            case "app.pause":
                self.manager.pause_all()
                await self._send(ws, {
                    "type": "session.list",
                    "sessions": self.manager.list(),
                })

            case "app.resume":
                await self.manager.resume_all()
                await self._send(ws, {
                    "type": "session.list",
                    "sessions": self.manager.list(),
                })

            case "session.remove":
                session_id = req.get("sessionId", "")
                if not self.manager.remove(session_id):
                    await self._send(ws, {
                        "type": "error",
                        "message": f"Session not found: {session_id}",
                        "requestType": msg_type,
                    })
                else:
                    await self._send(ws, {
                        "type": "session.removed",
                        "sessionId": session_id,
                    })

            case "session.list":
                await self._send(ws, {
                    "type": "session.list",
                    "sessions": self.manager.list(),
                })

            case _:
                response = {
                    "type": "error",
                    "message": f"Unknown request type: {msg_type}",
                    "requestType": msg_type,
                }
                source_dir = req.get("sourceDir")
                if isinstance(source_dir, str):
                    response["sourceDir"] = source_dir
                request_id = req.get("requestId")
                if isinstance(request_id, str):
                    response["requestId"] = request_id
                await self._send(ws, response)

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
        self._session_callbacks.setdefault(ws, {})[session.id] = on_event

    def _unsubscribe_all(self, ws: ServerConnection) -> None:
        callbacks = self._session_callbacks.pop(ws, {})
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


def _session_payload(session: AnySession | None) -> dict[str, Any] | None:
    if session is None:
        return None
    return asdict(session.to_info())
