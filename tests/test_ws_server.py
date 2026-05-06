"""Tests for the daemon WebSocket server — full integration through WS protocol."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
import websockets

from hf_agent_ui.daemon.pty_session import TOOL_COMMANDS
from hf_agent_ui.daemon.session_manager import SessionManager
from hf_agent_ui.daemon.ws_server import DaemonWsServer

MOCK_CLI = str(Path(__file__).parent / "mock_cli.py")


@pytest.fixture
def _register_mock_pty_tool():
    """Temporarily register a mock PTY command."""
    TOOL_COMMANDS["mock"] = [sys.executable, MOCK_CLI]
    yield
    del TOOL_COMMANDS["mock"]


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
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_create_pty_session_via_ws(tmp_path: Path) -> None:
    """Create a PTY session via WS and verify we get pty.created back."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)  # port 0 = random available port
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "pty.create",
                "workDir": str(tmp_path),
                "tool": "mock",
            })

            types = [m["type"] for m in msgs]
            assert "pty.created" in types

            created = next(m for m in msgs if m["type"] == "pty.created")
            assert created["session"]["tool"] == "mock"
            assert created["session"]["mode"] == "pty"
            assert created["session"]["status"] == "running"
            assert created["session"]["needs_input"] is False
            assert created["session"]["needs_input_reason"] is None

            session_id = created["session"]["id"]
            assert manager.get(session_id) is not None
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_create_custom_launch_pty_session_via_ws(tmp_path: Path) -> None:
    """Create a PTY session through a custom launch wrapper."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "pty.create",
                "workDir": str(tmp_path),
                "tool": "mock",
                "launchMode": "custom",
                "launchCommand": "{command}",
                "launchLabel": "gpu",
            })

            created = next(m for m in msgs if m["type"] == "pty.created")
            assert created["session"]["launch_mode"] == "custom"
            assert created["session"]["launch_command"] == "{command}"
            assert created["session"]["launch_label"] == "gpu"
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_create_custom_launch_requires_command_placeholder(tmp_path: Path) -> None:
    """Invalid custom launch templates should not leave a session record behind."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "pty.create",
                "workDir": str(tmp_path),
                "tool": "mock",
                "launchMode": "custom",
                "launchCommand": "srun --pty --chdir {workDir}",
            })

            error = next(m for m in msgs if m["type"] == "error")
            assert error["requestType"] == "pty.create"
            assert "{command}" in error["message"]
            assert manager.list() == []
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_send_pty_input_and_stream_output_via_ws(tmp_path: Path) -> None:
    """Send input via WS and verify terminal output comes back."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "pty.create",
                "workDir": str(tmp_path),
                "tool": "mock",
            })
            session_id = next(m for m in msgs if m["type"] == "pty.created")["session"]["id"]

            await ws.send(json.dumps({
                "type": "pty.input",
                "sessionId": session_id,
                "data": "test streaming\r",
            }))

            msgs = await _recv_until(
                ws,
                lambda m: m.get("type") == "pty.output" and "test streaming" in m.get("data", ""),
            )

            output = "".join(m.get("data", "") for m in msgs if m.get("type") == "pty.output")
            assert "test streaming" in output
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_session_list_via_ws(tmp_path: Path) -> None:
    """session.list should return all PTY sessions."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "mock"})
            await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "mock"})

            msgs = await _send_recv(ws, {"type": "session.list"})
            list_msg = next(m for m in msgs if m["type"] == "session.list")
            assert len(list_msg["sessions"]) == 2
            assert all(session["mode"] == "pty" for session in list_msg["sessions"])
            assert all(session["needs_input"] is False for session in list_msg["sessions"])
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_stop_session_via_ws(tmp_path: Path) -> None:
    """session.stop should stop the PTY session and emit pty.exit."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "mock"})
            session_id = next(m for m in msgs if m["type"] == "pty.created")["session"]["id"]

            await ws.send(json.dumps({"type": "session.stop", "sessionId": session_id}))
            msgs = await _recv_until(ws, lambda m: m.get("type") == "pty.exit")

            exit_msgs = [m for m in msgs if m["type"] == "pty.exit"]
            assert len(exit_msgs) == 1
            assert exit_msgs[0]["sessionId"] == session_id
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_remove_session_via_ws(tmp_path: Path) -> None:
    """session.remove should stop and remove the PTY session."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "mock"})
            session_id = next(m for m in msgs if m["type"] == "pty.created")["session"]["id"]

            await ws.send(json.dumps({"type": "session.remove", "sessionId": session_id}))
            msgs = await _recv_until(ws, lambda m: m.get("type") == "session.removed")

            removed = next(m for m in msgs if m["type"] == "session.removed")
            assert removed["sessionId"] == session_id
            assert manager.get(session_id) is None

            msgs = await _send_recv(ws, {"type": "session.list"})
            list_msg = next(m for m in msgs if m["type"] == "session.list")
            assert list_msg["sessions"] == []
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_input_required_event_and_clear_via_ws(tmp_path: Path) -> None:
    """Prompt-like output should mark input required until the user types."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "mock"})
            session_id = next(m for m in msgs if m["type"] == "pty.created")["session"]["id"]

            await ws.send(json.dumps({
                "type": "pty.input",
                "sessionId": session_id,
                "data": "__permission_prompt__\r",
            }))
            msgs = await _recv_until(ws, lambda m: m.get("type") == "session.input_required")
            required = next(m for m in msgs if m["type"] == "session.input_required")
            assert required["sessionId"] == session_id
            assert required["source"] == "pty"
            assert required["kind"] == "permission"
            assert required["title"] == "Permission required"
            assert required["message"] == "Permission required"
            assert isinstance(required["detectedAt"], str)
            assert "permission" in required["reason"].lower()

            await ws.send(json.dumps({
                "type": "pty.input",
                "sessionId": session_id,
                "data": "y\r",
            }))
            msgs = await _recv_until(ws, lambda m: m.get("type") == "session.input_resolved")
            resolved = next(m for m in msgs if m["type"] == "session.input_resolved")
            assert resolved["sessionId"] == session_id
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_subscribe_replays_buffered_pty_output(tmp_path: Path) -> None:
    """A refreshed browser can subscribe and receive recent PTY output."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "mock"})
            session_id = next(m for m in msgs if m["type"] == "pty.created")["session"]["id"]

            await ws.send(json.dumps({
                "type": "pty.input",
                "sessionId": session_id,
                "data": "buffer me\r",
            }))
            await _recv_until(
                ws,
                lambda m: m.get("type") == "pty.output" and "buffer me" in m.get("data", ""),
            )

        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "session.subscribe",
                "sessionId": session_id,
            })
            subscribed = next(m for m in msgs if m["type"] == "session.subscribed")
            output = "".join(m.get("data", "") for m in msgs if m.get("type") == "pty.output")
            assert subscribed["session"]["id"] == session_id
            assert "buffer me" in output
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_pause_and_resume_session_via_ws(tmp_path: Path) -> None:
    """Paused PTY sessions should keep their HF Agent UI id and resume into a running process."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "mock"})
            session_id = next(m for m in msgs if m["type"] == "pty.created")["session"]["id"]

            await ws.send(json.dumps({"type": "session.pause", "sessionId": session_id}))
            msgs = await _recv_until(ws, lambda m: m.get("type") == "session.paused")
            paused = next(m for m in msgs if m["type"] == "session.paused")
            assert paused["sessionId"] == session_id
            assert paused["session"]["status"] == "paused"

            await asyncio.sleep(0.3)
            assert manager.get(session_id).to_info().status == "paused"

            await ws.send(json.dumps({"type": "session.resume", "sessionId": session_id}))
            msgs = await _recv_until(ws, lambda m: m.get("type") == "session.resumed")
            resumed = next(m for m in msgs if m["type"] == "session.resumed")
            assert resumed["sessionId"] == session_id
            assert resumed["session"]["status"] == "running"
            assert manager.get(session_id).to_info().status == "running"
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
async def test_error_on_unknown_pty_session(tmp_path: Path) -> None:
    """Sending input to a nonexistent PTY session should return an error."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "pty.input",
                "sessionId": "nonexistent-id",
                "data": "hello",
            })
            error = next(m for m in msgs if m["type"] == "error")
            assert "not found" in error["message"].lower()
    finally:
        manager.stop_all()
        await server.stop()
