from __future__ import annotations

import asyncio
import json
import logging
import platform
import re
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import websockets

from .session_manager import SessionManager
from .ws_server import MAX_WS_MESSAGE_BYTES, DaemonWsServer

logger = logging.getLogger(__name__)
HOST_TOKEN_HEADER = "X-HF-Agent-UI-Host-Token"


class HubDaemonClient:
    """Maintains the agent host's outbound WebSocket connection to the hub."""

    def __init__(
        self,
        manager: SessionManager,
        hub_url: str,
        daemon_name: str,
        token: str | None = None,
        hf_token: str | None = None,
    ) -> None:
        self.manager = manager
        self.hub_url = hub_url.rstrip("/")
        self.daemon_name = daemon_name
        self.token = token
        self.hf_token = hf_token
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        backoff = 1.0
        while self._running:
            try:
                await self._connect_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._is_missing_hf_space_auth_error(exc):
                    status_code = _websocket_status_code(exc)
                    status_suffix = f" with HTTP {status_code}" if status_code else ""
                    logger.error(
                        "Hub connection failed%s, retrying in %.0fs. Private Hugging Face Spaces require "
                        "HF_TOKEN or --hf-token in addition to --token; without it, Hugging Face rejects the "
                        "WebSocket before hf-agent-ui sees the request.",
                        status_suffix,
                        backoff,
                    )
                else:
                    logger.exception("Hub connection failed, retrying in %.0fs", backoff)

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def stop(self) -> None:
        self._running = False

    async def _connect_once(self) -> None:
        ws_url = _daemon_ws_url(self.hub_url)
        headers = _auth_headers(self.hf_token, host_token=self.token)
        logger.info("Connecting to hub at %s", _daemon_ws_url(self.hub_url))

        async with websockets.connect(
            ws_url,
            additional_headers=headers,
            max_size=MAX_WS_MESSAGE_BYTES,
        ) as ws:
            await ws.send(json.dumps({
                "type": "daemon.register",
                "name": self.daemon_name,
                "hostname": platform.node(),
            }))
            registered = json.loads(await ws.recv())
            if registered.get("type") != "daemon.registered":
                raise RuntimeError(f"Hub rejected agent host registration: {registered}")
            logger.info("Registered with hub as %s (id=%s)", self.daemon_name, registered.get("daemonId"))

            handler = DaemonWsServer(self.manager, port=0)
            handler._subscriptions[ws] = set()  # type: ignore[index]
            try:
                async for raw in ws:
                    await self._handle_hub_message(handler, ws, raw)
            finally:
                handler._unsubscribe_all(ws)  # type: ignore[arg-type]
                handler._subscriptions.pop(ws, None)  # type: ignore[arg-type]

    @staticmethod
    async def _handle_hub_message(handler: DaemonWsServer, ws: Any, raw: str) -> None:
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            await handler._send(ws, {"type": "error", "message": "Invalid JSON"})
            return
        await handler._handle_request(ws, req)

    def _is_missing_hf_space_auth_error(self, exc: Exception) -> bool:
        return _is_hf_space_url(self.hub_url) and not self.hf_token and _websocket_status_code(exc) in {401, 403, 404}


def _daemon_ws_url(hub_url: str, query_token: str | None = None) -> str:
    parsed = urlsplit(hub_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/")
    path = f"{path}/daemon/ws" if path else "/daemon/ws"
    query = urlencode({"token": query_token}) if query_token else ""
    return urlunsplit((scheme, parsed.netloc, path, query, ""))


def _auth_headers(hf_token: str | None, host_token: str | None = None) -> dict[str, str] | None:
    headers: dict[str, str] = {}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    if host_token:
        headers[HOST_TOKEN_HEADER] = host_token
    return headers or None


def _is_hf_space_url(hub_url: str) -> bool:
    return urlsplit(hub_url).netloc.endswith(".hf.space")


def _websocket_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    for attr in ("status_code", "status"):
        response_status = getattr(response, attr, None)
        if isinstance(response_status, int):
            return response_status

    match = re.search(r"HTTP\s+(\d{3})", str(exc))
    if match:
        return int(match.group(1))
    return None
