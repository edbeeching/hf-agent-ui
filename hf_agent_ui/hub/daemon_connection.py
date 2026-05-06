from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine

from fastapi import WebSocket, WebSocketDisconnect, status

from .daemon_registry import DaemonInfo, DaemonRegistry
from .security import UserIdentity, current_host_ws_user

logger = logging.getLogger(__name__)

MessageCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class DaemonConnection:
    """An agent-host-held WebSocket connection to the hub."""

    def __init__(self, daemon: DaemonInfo, ws: WebSocket, on_message: MessageCallback) -> None:
        self.daemon = daemon
        self._ws = ws
        self._on_message = on_message

    async def run(self) -> None:
        async for raw in self._ws.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from daemon %s", self.daemon.name)
                continue
            logger.debug("from daemon %s: %s", self.daemon.name, msg.get("type", "?"))
            await self._on_message(self.daemon.id, msg)

    async def send(self, data: dict[str, Any]) -> None:
        await self._ws.send_text(json.dumps(data, default=str))

    async def close(self) -> None:
        try:
            await self._ws.close()
        except RuntimeError:
            pass


class DaemonConnectionPool:
    """Tracks outbound daemon connections initiated by daemon processes."""

    def __init__(self, registry: DaemonRegistry, on_message: MessageCallback) -> None:
        self.registry = registry
        self._connections: dict[str, DaemonConnection] = {}
        self._on_message = on_message

    async def handle_daemon(self, ws: WebSocket, expected_token: str | None = None) -> None:
        owner = current_host_ws_user(ws, expected_token)
        if owner is None:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await ws.accept()
        daemon: DaemonInfo | None = None
        conn: DaemonConnection | None = None

        try:
            register_msg = await ws.receive_text()
            register_payload = json.loads(register_msg)
            if not isinstance(register_payload, dict):
                raise ValueError("daemon.register payload must be an object")
            name = self._daemon_name(register_payload)
            duplicate = self._connected_daemon_by_name(name, owner.sub)
            if duplicate:
                await _send_error(ws, f"Agent host name already connected: {name}")
                return
            daemon = self._register(register_payload, name, owner)
            conn = DaemonConnection(daemon, ws, self._on_message)
            self._connections[daemon.id] = conn
            await conn.send({
                "type": "daemon.registered",
                "daemonId": daemon.id,
                "name": daemon.name,
            })
            logger.info("Agent host %s connected over outbound WebSocket", daemon.name)
            await conn.run()
        except (json.JSONDecodeError, ValueError) as exc:
            await _send_error(ws, str(exc))
        except WebSocketDisconnect:
            pass
        finally:
            if daemon and self._connections.get(daemon.id) is conn:
                self._connections.pop(daemon.id, None)
                self.registry.remove(daemon.id)
                logger.info("Agent host %s disconnected", daemon.name)

    async def send(self, daemon_id: str, data: dict[str, Any]) -> None:
        conn = self._connections.get(daemon_id)
        if not conn:
            raise RuntimeError(f"No connection to agent host {daemon_id}")
        await conn.send(data)

    def is_connected(self, daemon_id: str) -> bool:
        return daemon_id in self._connections

    def owns(self, daemon_id: str, owner_sub: str) -> bool:
        return self.registry.owns(daemon_id, owner_sub)

    async def disconnect_all(self) -> None:
        for conn in list(self._connections.values()):
            await conn.close()
        self._connections.clear()

    def _connected_daemon_by_name(self, name: str, owner_sub: str) -> DaemonConnection | None:
        for conn in self._connections.values():
            if conn.daemon.name == name and conn.daemon.owner_sub == owner_sub:
                return conn
        return None

    @staticmethod
    def _daemon_name(msg: dict[str, Any]) -> str:
        if msg.get("type") != "daemon.register":
            raise ValueError("First daemon message must be daemon.register")
        name = msg.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("daemon.register requires a non-empty name")
        return name.strip()

    def _register(self, msg: dict[str, Any], name: str, owner: UserIdentity) -> DaemonInfo:
        hostname = msg.get("hostname")
        if not isinstance(hostname, str):
            hostname = ""
        return self.registry.register(name, "outbound", 0, hostname, owner=owner)


async def _send_error(ws: WebSocket, message: str) -> None:
    try:
        await ws.send_text(json.dumps({"type": "error", "message": message}))
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
    except RuntimeError:
        pass
