from __future__ import annotations

from collections import defaultdict, deque
import json
import logging
from typing import Any, Deque

from fastapi import WebSocket, WebSocketDisconnect

from .daemon_connection import DaemonConnectionPool
from .security import UserIdentity

logger = logging.getLogger(__name__)


class WsRelay:
    """
    Browser-facing WebSocket relay.

    Receives messages from browsers, routes them to the correct daemon.
    Receives messages from daemons (via pool callback), routes to subscribed browsers.

    Browser protocol:
      -> { type: "pty.create", daemonId, workDir, tool?, cols?, rows?, yoloMode? }
      -> { type: "pty.input", daemonId, sessionId, data }
      -> { type: "pty.resize", daemonId, sessionId, cols, rows }
      -> { type: "session.image.send", daemonId, sessionId, filename, mimeType, dataBase64, prompt }
      -> { type: "session.stop", daemonId, sessionId }
      -> { type: "session.rename", daemonId, sessionId, label? }
      -> { type: "session.mark_seen", daemonId, sessionId }
      -> { type: "session.list", daemonId }
      -> { type: "session.subscribe", daemonId, sessionId }
      -> { type: "worktrees.list", daemonId, sourceDir, requestId? }

      <- { type: "pty.created", daemonId, session }
      <- { type: "pty.output", daemonId, sessionId, data }
      <- { type: "pty.exit", daemonId, sessionId, code }
      <- { type: "session.image.sent", daemonId, sessionId, path, mimeType, size, session }
      <- { type: "session.input_required", daemonId, sessionId, reason, source, kind?, title?, message?, detectedAt? }
      <- { type: "session.input_resolved", daemonId, sessionId }
      <- { type: "session.subscribed", daemonId, session }
      <- { type: "session.renamed", daemonId, sessionId, session }
      <- { type: "session.updated", daemonId, sessionId, session }
      <- { type: "session.list", daemonId, sessions }
      <- { type: "worktrees.list", daemonId, sourceDir, requestId?, worktrees }
      <- { type: "error", message }
    """

    def __init__(self, pool: DaemonConnectionPool) -> None:
        self.pool = pool
        self._clients: set[WebSocket] = set()
        self._client_owners: dict[WebSocket, str] = {}
        self._session_subscribers: dict[tuple[str, str], set[WebSocket]] = defaultdict(set)
        self._pending_requests: dict[tuple[str, str], Deque[WebSocket]] = defaultdict(deque)
        self._pending_worktree_requests: dict[tuple[str, str], WebSocket] = {}

    async def handle_browser(self, ws: WebSocket, user: UserIdentity) -> None:
        await ws.accept()
        self._clients.add(ws)
        self._client_owners[ws] = user.sub
        logger.info("Browser connected as %s", user.username)
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
            self._client_owners.pop(ws, None)
            self._remove_client(ws)

    async def _handle_browser_message(self, ws: WebSocket, req: dict[str, Any]) -> None:
        daemon_id = req.get("daemonId")
        if not daemon_id:
            await self._send_to_browser(ws, {"type": "error", "message": "Missing daemonId"})
            return

        daemon_id = str(daemon_id)
        owner_sub = self._client_owners.get(ws)
        if not owner_sub or not self.pool.owns(daemon_id, owner_sub):
            error = {
                "type": "error",
                "message": f"No connection to agent host {daemon_id}",
                "requestType": req.get("type"),
                "daemonId": daemon_id,
            }
            _copy_request_context(req, error)
            await self._send_to_browser(ws, error)
            return
        self._track_browser_request(ws, daemon_id, req)
        # Forward to daemon, stripping daemonId (daemon doesn't need it)
        daemon_msg = {k: v for k, v in req.items() if k != "daemonId"}
        try:
            await self.pool.send(daemon_id, daemon_msg)
        except RuntimeError as e:
            self._untrack_browser_request(ws, daemon_id, req)
            error = {
                "type": "error",
                "message": str(e),
                "requestType": req.get("type"),
                "daemonId": daemon_id,
            }
            _copy_request_context(req, error)
            await self._send_to_browser(ws, error)

    async def on_daemon_message(self, daemon_id: str, msg: dict[str, Any]) -> None:
        """Called by the connection pool when a daemon sends a message."""
        # Inject daemonId so browser knows which daemon it came from
        msg["daemonId"] = daemon_id
        targets = self._targets_for_daemon_message(daemon_id, msg)
        logger.debug("relay to %d browsers: %s", len(targets), msg.get("type", "?"))
        await self._send_to_targets(targets, msg)

    async def _send_to_targets(self, targets: set[WebSocket], data: dict[str, Any]) -> None:
        payload = json.dumps(data, default=str)
        disconnected = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self._clients.discard(ws)
            self._remove_client(ws)

    def _track_browser_request(self, ws: WebSocket, daemon_id: str, req: dict[str, Any]) -> None:
        msg_type = req.get("type")
        session_id = req.get("sessionId")

        if msg_type == "pty.create":
            self._pending_requests[(daemon_id, "pty.create")].append(ws)
            return

        if msg_type in {"session.list", "app.pause", "app.resume"}:
            self._pending_requests[(daemon_id, "session.list")].append(ws)
            return

        if msg_type == "worktrees.list":
            request_id = _request_id(req)
            if request_id:
                self._pending_worktree_requests[(daemon_id, request_id)] = ws
            else:
                self._pending_requests[(daemon_id, "worktrees.list")].append(ws)
            return

        if msg_type == "session.image.send":
            self._pending_requests[(daemon_id, "session.image.send")].append(ws)
            if isinstance(session_id, str) and session_id:
                self._session_subscribers[(daemon_id, session_id)].add(ws)
            return

        if msg_type in {"session.rename", "session.mark_seen"}:
            self._pending_requests[(daemon_id, msg_type)].append(ws)
            if isinstance(session_id, str) and session_id:
                self._session_subscribers[(daemon_id, session_id)].add(ws)
            return

        if isinstance(session_id, str) and session_id:
            self._session_subscribers[(daemon_id, session_id)].add(ws)

    def _targets_for_daemon_message(self, daemon_id: str, msg: dict[str, Any]) -> set[WebSocket]:
        msg_type = msg.get("type")
        session_id = _session_id(msg)

        if msg_type == "pty.started":
            target = self._peek_pending(daemon_id, "pty.create")
            if target and session_id:
                self._session_subscribers[(daemon_id, session_id)].add(target)
                return {target}
            return set()

        if msg_type == "pty.created":
            target = self._pop_pending(daemon_id, "pty.create")
            created_session_id = _session_id(msg)
            if target and created_session_id:
                self._session_subscribers[(daemon_id, created_session_id)].add(target)
            return {target} if target else set()

        if msg_type == "session.list":
            target = self._pop_pending(daemon_id, "session.list")
            return {target} if target else set()

        if msg_type == "worktrees.list":
            target = self._pop_pending_worktree_request(daemon_id, msg)
            return {target} if target else set()

        if msg_type == "session.subscribed":
            if session_id:
                return set(self._session_subscribers.get((daemon_id, session_id), set()))
            return set()

        if msg_type == "session.image.sent":
            targets = set(self._session_subscribers.get((daemon_id, session_id), set())) if session_id else set()
            target = self._pop_pending(daemon_id, "session.image.send")
            if target:
                targets.add(target)
            return targets

        if msg_type == "session.renamed":
            targets = set(self._session_subscribers.get((daemon_id, session_id), set())) if session_id else set()
            target = self._pop_pending(daemon_id, "session.rename")
            if target:
                targets.add(target)
            return targets

        if msg_type == "session.updated":
            targets = set(self._session_subscribers.get((daemon_id, session_id), set())) if session_id else set()
            target = self._pop_pending(daemon_id, "session.mark_seen")
            if target:
                targets.add(target)
            return targets

        if msg_type == "error":
            request_type = msg.get("requestType")
            if isinstance(request_type, str):
                if request_type == "worktrees.list":
                    target = self._pop_pending_worktree_request(daemon_id, msg)
                    if target:
                        return {target}
                    return set()
                target = self._pop_pending(daemon_id, request_type)
                if target:
                    return {target}

        if session_id:
            return set(self._session_subscribers.get((daemon_id, session_id), set()))
        return set()

    def _pop_pending(self, daemon_id: str, request_type: str) -> WebSocket | None:
        pending = self._pending_requests.get((daemon_id, request_type))
        while pending:
            ws = pending.popleft()
            if ws in self._clients:
                return ws
        return None

    def _peek_pending(self, daemon_id: str, request_type: str) -> WebSocket | None:
        pending = self._pending_requests.get((daemon_id, request_type))
        while pending:
            ws = pending[0]
            if ws in self._clients:
                return ws
            pending.popleft()
        return None

    def _pop_pending_worktree_request(self, daemon_id: str, msg: dict[str, Any]) -> WebSocket | None:
        request_id = _request_id(msg)
        if request_id:
            target = self._pending_worktree_requests.pop((daemon_id, request_id), None)
            if target in self._clients:
                return target
            return None
        return self._pop_pending(daemon_id, "worktrees.list")

    def _untrack_browser_request(self, ws: WebSocket, daemon_id: str, req: dict[str, Any]) -> None:
        if req.get("type") != "worktrees.list":
            return
        request_id = _request_id(req)
        if request_id:
            if self._pending_worktree_requests.get((daemon_id, request_id)) is ws:
                self._pending_worktree_requests.pop((daemon_id, request_id), None)
            return
        pending = self._pending_requests.get((daemon_id, "worktrees.list"))
        if not pending:
            return
        try:
            pending.remove(ws)
        except ValueError:
            pass

    def _remove_client(self, ws: WebSocket) -> None:
        for subscribers in self._session_subscribers.values():
            subscribers.discard(ws)
        for key, target in list(self._pending_worktree_requests.items()):
            if target is ws:
                self._pending_worktree_requests.pop(key, None)
        for pending in self._pending_requests.values():
            try:
                while True:
                    pending.remove(ws)
            except ValueError:
                pass

    @staticmethod
    async def _send_to_browser(ws: WebSocket, data: dict[str, Any]) -> None:
        try:
            await ws.send_text(json.dumps(data, default=str))
        except Exception:
            pass


def _session_id(msg: dict[str, Any]) -> str | None:
    session_id = msg.get("sessionId")
    if isinstance(session_id, str) and session_id:
        return session_id
    session = msg.get("session")
    if isinstance(session, dict):
        nested = session.get("id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _request_id(msg: dict[str, Any]) -> str | None:
    request_id = msg.get("requestId")
    return request_id if isinstance(request_id, str) and request_id else None


def _copy_request_context(source: dict[str, Any], target: dict[str, Any]) -> None:
    request_id = source.get("requestId")
    if isinstance(request_id, str):
        target["requestId"] = request_id
    source_dir = source.get("sourceDir")
    if isinstance(source_dir, str):
        target["sourceDir"] = source_dir
