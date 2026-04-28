"""Tests for the daemon WebSocket server — full integration through WS protocol."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import websockets

from switch.daemon.adapters import ADAPTERS, ToolAdapter
from switch.daemon.session import SessionOptions
from switch.daemon.session_manager import SessionManager
from switch.daemon.ws_server import DaemonWsServer

MOCK_CLI = str(Path(__file__).parent / "mock_cli.py")


class MockAdapter(ToolAdapter):
    name = "mock"

    def build_start_args(self, opts: SessionOptions, initial_prompt: str | None = None) -> list[str]:
        return [sys.executable, MOCK_CLI]

    def format_user_message(self, message: str) -> str | None:
        return json.dumps({"type": "user_message", "content": message})

    def format_control_response(self, response: dict[str, Any]) -> str | None:
        return json.dumps(response)

    def parse_output_line(self, line: str) -> dict[str, Any] | None:
        if not line.strip():
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"type": "raw", "text": line}

    def supports_stdin_messages(self) -> bool:
        return True

    def build_resume_args(self, codex_session_id: str, message: str, opts: SessionOptions) -> list[str]:
        raise NotImplementedError


@pytest.fixture
def _register_mock_adapter():
    """Temporarily register the mock adapter so get_adapter("mock") works."""
    ADAPTERS["mock"] = MockAdapter
    yield
    del ADAPTERS["mock"]


async def _send_recv(ws, data: dict) -> list[dict]:
    """Send a message and collect responses for a short window."""
    await ws.send(json.dumps(data))
    messages = []
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            messages.append(json.loads(raw))
    except (asyncio.TimeoutError, TimeoutError):
        pass
    return messages


async def _recv_until(ws, predicate, timeout=3.0) -> list[dict]:
    """Collect messages until predicate returns True on one of them, or timeout."""
    messages = []
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, remaining))
            msg = json.loads(raw)
            messages.append(msg)
            if predicate(msg):
                return messages
    except (asyncio.TimeoutError, TimeoutError):
        pass
    return messages


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_adapter")
async def test_create_session_via_ws(tmp_path: Path) -> None:
    """Create a session via WS and verify we get session.created back."""
    manager = SessionManager()
    server = DaemonWsServer(manager, 0)  # port 0 = random available port
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "session.create",
                "workDir": str(tmp_path),
                "tool": "mock",
            })

            # Should get session.created, session.started, and session.message (init)
            types = [m["type"] for m in msgs]
            assert "session.created" in types

            created = next(m for m in msgs if m["type"] == "session.created")
            assert created["session"]["tool"] == "mock"
            assert created["session"]["status"] == "running"

            session_id = created["session"]["id"]
            assert manager.get(session_id) is not None
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_adapter")
async def test_send_message_and_stream_via_ws(tmp_path: Path) -> None:
    """Send a message via WS and verify stream events come back."""
    manager = SessionManager()
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            # Create session
            msgs = await _send_recv(ws, {
                "type": "session.create",
                "workDir": str(tmp_path),
                "tool": "mock",
            })
            session_id = next(m for m in msgs if m["type"] == "session.created")["session"]["id"]

            # Send a message and collect responses
            await ws.send(json.dumps({
                "type": "session.send",
                "sessionId": session_id,
                "message": "test streaming",
            }))

            # Wait for a result event
            msgs = await _recv_until(
                ws,
                lambda m: m.get("type") == "session.message" and m.get("data", {}).get("type") == "result",
            )

            data_types = [m.get("data", {}).get("type") for m in msgs if m.get("type") == "session.message"]
            assert "stream_event" in data_types, f"Expected stream_event in {data_types}"
            assert "result" in data_types, f"Expected result in {data_types}"

            # Verify the echo content
            result_msg = next(
                m for m in msgs
                if m.get("type") == "session.message" and m.get("data", {}).get("type") == "result"
            )
            assert "test streaming" in result_msg["data"]["text"]
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_adapter")
async def test_session_list_via_ws(tmp_path: Path) -> None:
    """session.list should return all sessions."""
    manager = SessionManager()
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            # Create two sessions
            await _send_recv(ws, {"type": "session.create", "workDir": str(tmp_path), "tool": "mock"})
            await _send_recv(ws, {"type": "session.create", "workDir": str(tmp_path), "tool": "mock"})

            # List sessions
            msgs = await _send_recv(ws, {"type": "session.list"})
            list_msg = next(m for m in msgs if m["type"] == "session.list")
            assert len(list_msg["sessions"]) == 2
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_adapter")
async def test_stop_session_via_ws(tmp_path: Path) -> None:
    """session.stop should stop the session and emit exit."""
    manager = SessionManager()
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {"type": "session.create", "workDir": str(tmp_path), "tool": "mock"})
            session_id = next(m for m in msgs if m["type"] == "session.created")["session"]["id"]

            # Stop and collect exit event
            await ws.send(json.dumps({"type": "session.stop", "sessionId": session_id}))
            msgs = await _recv_until(ws, lambda m: m.get("type") == "session.exit")

            exit_msgs = [m for m in msgs if m["type"] == "session.exit"]
            assert len(exit_msgs) == 1
            assert exit_msgs[0]["sessionId"] == session_id
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_adapter")
async def test_error_on_unknown_session(tmp_path: Path) -> None:
    """Sending to a nonexistent session should return an error."""
    manager = SessionManager()
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "session.send",
                "sessionId": "nonexistent-id",
                "message": "hello",
            })
            error = next(m for m in msgs if m["type"] == "error")
            assert "not found" in error["message"].lower()
    finally:
        manager.stop_all()
        await server.stop()
