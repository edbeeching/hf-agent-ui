"""Tests for the daemon WebSocket server — full integration through WS protocol."""
from __future__ import annotations

import asyncio
import base64
import json
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import websockets

from hf_agent_ui.daemon.pty_session import TOOL_COMMANDS
from hf_agent_ui.daemon.session_manager import SessionManager
from hf_agent_ui.daemon.ws_server import DaemonWsServer

MOCK_CLI = str(Path(__file__).parent / "mock_cli.py")
PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png"


@pytest.fixture
def _register_mock_pty_tool():
    """Temporarily register a mock PTY command."""
    TOOL_COMMANDS["mock"] = [sys.executable, MOCK_CLI]
    yield
    del TOOL_COMMANDS["mock"]


@pytest.fixture
def _mock_codex_tool():
    """Temporarily point the default Codex tool at the mock CLI."""
    original = TOOL_COMMANDS["codex"]
    TOOL_COMMANDS["codex"] = [sys.executable, MOCK_CLI]
    yield
    TOOL_COMMANDS["codex"] = original


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
            assert created["session"]["label"] is None
            assert created["session"]["agent_state"] in {"idle", "working"}
            assert "git" in created["session"]
            assert created["session"]["needs_input"] is False
            assert created["session"]["needs_input_reason"] is None

            session_id = created["session"]["id"]
            assert manager.get(session_id) is not None
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_rename_and_mark_seen_session_via_ws(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "mock"})
            session_id = next(m for m in msgs if m["type"] == "pty.created")["session"]["id"]

            msgs = await _send_recv(ws, {
                "type": "session.rename",
                "sessionId": session_id,
                "label": "Backend cleanup",
            })
            renamed = next(m for m in msgs if m["type"] == "session.renamed")
            assert renamed["sessionId"] == session_id
            assert renamed["session"]["label"] == "Backend cleanup"

            session = manager.get(session_id)
            assert session is not None
            activity_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
            session.last_activity_at = activity_at
            session.done_since = activity_at

            msgs = await _send_recv(ws, {
                "type": "session.mark_seen",
                "sessionId": session_id,
            })
            updated = next(m for m in msgs if m["type"] == "session.updated")
            assert updated["session"]["done_since"] is None
            assert updated["session"]["last_seen_at"] is not None
            assert updated["session"]["agent_state"] != "done"
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_codex_tool")
async def test_create_pty_session_defaults_to_codex_via_ws(tmp_path: Path) -> None:
    """Omitting tool from pty.create starts the default Codex session."""
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "pty.create",
                "workDir": str(tmp_path),
            })

            created = next(m for m in msgs if m["type"] == "pty.created")
            assert created["session"]["tool"] == "codex"
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_codex_tool")
async def test_create_codex_yolo_session_via_ws(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "pty.create",
                "workDir": str(tmp_path),
                "tool": "codex",
                "yoloMode": True,
            })

            created = next(m for m in msgs if m["type"] == "pty.created")
            assert created["session"]["tool"] == "codex"
            assert created["session"]["yolo_mode"] is True
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_codex_tool")
async def test_create_pty_session_ignores_non_boolean_yolo_mode(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "pty.create",
                "workDir": str(tmp_path),
                "tool": "codex",
                "yoloMode": "true",
            })

            created = next(m for m in msgs if m["type"] == "pty.created")
            assert created["session"]["yolo_mode"] is False
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
async def test_create_worktree_session_cleans_up_if_start_fails(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "scratch"
    source_dir.mkdir()
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "pty.create",
                "workDir": str(source_dir),
                "tool": "mock",
                "worktree": {
                    "enabled": True,
                    "sourceDir": str(source_dir),
                    "branch": "agent/missing-source",
                    "startPoint": "HEAD",
                },
            })

            error = next(m for m in msgs if m["type"] == "error")
            assert error["requestType"] == "pty.create"
            assert manager.list() == []
            assert not (repo / ".worktrees" / "agent-missing-source").exists()
            assert _git(repo, "show-ref", "--verify", "--quiet", "refs/heads/agent/missing-source").returncode == 1
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
async def test_list_existing_worktrees_via_ws(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "scratch"
    source_dir.mkdir()
    (source_dir / "README.md").write_text("scratch\n", encoding="utf-8")
    _git(repo, "add", ".", check=True)
    _git(repo, "commit", "-m", "add scratch", check=True)
    existing_root = repo / ".worktrees" / "feature-ws-list"
    _git(repo, "worktree", "add", "-b", "feature/ws-list", str(existing_root), "HEAD", check=True)
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "worktrees.list",
                "sourceDir": str(source_dir),
                "requestId": "req-list",
            })

            list_msg = next(m for m in msgs if m["type"] == "worktrees.list")
            assert list_msg["sourceDir"] == str(source_dir)
            assert list_msg["requestId"] == "req-list"
            assert len(list_msg["worktrees"]) == 1
            item = list_msg["worktrees"][0]
            assert item["branch"] == "feature/ws-list"
            assert item["worktree_root"] == str(existing_root.resolve())
            assert item["work_dir"] == str((existing_root / "scratch").resolve())
            assert item["available"] is True
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_create_existing_worktree_session_via_ws(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    source_dir = repo / "scratch"
    source_dir.mkdir()
    (source_dir / "README.md").write_text("scratch\n", encoding="utf-8")
    _git(repo, "add", ".", check=True)
    _git(repo, "commit", "-m", "add scratch", check=True)
    existing_root = repo / ".worktrees" / "feature-ws-attach"
    _git(repo, "worktree", "add", "-b", "feature/ws-attach", str(existing_root), "HEAD", check=True)
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "pty.create",
                "workDir": str(source_dir),
                "tool": "mock",
                "worktree": {
                    "enabled": True,
                    "mode": "existing",
                    "sourceDir": str(source_dir),
                    "worktreeRoot": str(existing_root),
                },
            })

            created = next(m for m in msgs if m["type"] == "pty.created")
            assert created["session"]["work_dir"] == str((existing_root / "scratch").resolve())
            assert created["session"]["worktree"]["branch"] == "feature/ws-attach"
            assert created["session"]["worktree"]["managed"] is False
            assert existing_root.is_dir()
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
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_resume_missing_work_dir_returns_error_and_keeps_ws_alive(tmp_path: Path) -> None:
    work_dir = tmp_path / "gone"
    work_dir.mkdir()
    manager = SessionManager(tmp_path / "state.json")
    session = manager.create_pty(str(work_dir), tool="mock")
    shutil.rmtree(work_dir)
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {
                "type": "session.resume",
                "sessionId": session.id,
            })
            error = next(m for m in msgs if m["type"] == "error")
            assert error["requestType"] == "session.resume"
            assert error["sessionId"] == session.id

            msgs = await _send_recv(ws, {"type": "session.list"})
            list_msg = next(m for m in msgs if m["type"] == "session.list")
            assert [item["id"] for item in list_msg["sessions"]] == [session.id]
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_codex_tool")
async def test_send_session_image_to_codex_via_ws(monkeypatch, tmp_path: Path) -> None:
    """Pasted screenshots should be saved privately and used to relaunch Codex with an image."""
    monkeypatch.setenv("HF_AGENT_UI_ASSET_CACHE_DIR", str(tmp_path / "assets"))
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "codex"})
            session_id = next(m for m in msgs if m["type"] == "pty.created")["session"]["id"]

            await ws.send(json.dumps({
                "type": "session.image.send",
                "sessionId": session_id,
                "filename": "screenshot.png",
                "mimeType": "image/png",
                "dataBase64": base64.b64encode(PNG_BYTES).decode(),
                "prompt": "Use this screenshot",
            }))
            msgs = await _recv_until(ws, lambda m: m.get("type") == "session.image.sent")

            sent = next(m for m in msgs if m["type"] == "session.image.sent")
            image_path = Path(sent["path"])
            assert sent["sessionId"] == session_id
            assert sent["mimeType"] == "image/png"
            assert sent["size"] == len(PNG_BYTES)
            assert image_path.read_bytes() == PNG_BYTES
            assert stat.S_IMODE(image_path.stat().st_mode) == 0o600
            assert manager.get(session_id).status == "running"
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_register_mock_pty_tool")
async def test_send_session_image_rejects_non_codex_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HF_AGENT_UI_ASSET_CACHE_DIR", str(tmp_path / "assets"))
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "mock"})
            session_id = next(m for m in msgs if m["type"] == "pty.created")["session"]["id"]

            msgs = await _send_recv(ws, {
                "type": "session.image.send",
                "sessionId": session_id,
                "filename": "screenshot.png",
                "mimeType": "image/png",
                "dataBase64": base64.b64encode(PNG_BYTES).decode(),
                "prompt": "Use this screenshot",
            })

            error = next(m for m in msgs if m["type"] == "error")
            assert error["requestType"] == "session.image.send"
            assert "Codex" in error["message"]
            assert not (tmp_path / "assets").exists()
    finally:
        manager.stop_all()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_codex_tool")
async def test_send_session_image_rejects_invalid_image(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HF_AGENT_UI_ASSET_CACHE_DIR", str(tmp_path / "assets"))
    manager = SessionManager(tmp_path / "state.json")
    server = DaemonWsServer(manager, 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]

    try:
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            msgs = await _send_recv(ws, {"type": "pty.create", "workDir": str(tmp_path), "tool": "codex"})
            session_id = next(m for m in msgs if m["type"] == "pty.created")["session"]["id"]

            msgs = await _send_recv(ws, {
                "type": "session.image.send",
                "sessionId": session_id,
                "filename": "screenshot.jpg",
                "mimeType": "image/jpeg",
                "dataBase64": base64.b64encode(PNG_BYTES).decode(),
                "prompt": "Use this screenshot",
            })

            error = next(m for m in msgs if m["type"] == "error")
            assert error["requestType"] == "session.image.send"
            assert "MIME" in error["message"]
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


def _init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "init", check=True)
    _git(path, "config", "user.email", "test@example.com", check=True)
    _git(path, "config", "user.name", "Test User", check=True)
    _git(path, "add", ".", check=True)
    _git(path, "commit", "-m", "initial", check=True)
    return path


def _git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )
