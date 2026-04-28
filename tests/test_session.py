"""Tests for Session streaming using a mock CLI subprocess."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from switch.daemon.adapters import ToolAdapter
from switch.daemon.session import Session, SessionOptions, SessionStatus

MOCK_CLI = str(Path(__file__).parent / "mock_cli.py")


class MockAdapter(ToolAdapter):
    """Adapter that spawns our mock CLI script instead of claude/codex."""
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
def opts(tmp_path: Path) -> SessionOptions:
    return SessionOptions(work_dir=str(tmp_path), tool="mock")


@pytest.mark.asyncio
async def test_session_starts_and_receives_init(opts: SessionOptions) -> None:
    """Session should start, receive system/init event, and go to RUNNING status."""
    session = Session(opts, MockAdapter())
    events: list[dict] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    session.on_event(collect)
    await session.start()

    # Give the mock CLI time to emit system/init
    await asyncio.sleep(0.3)

    assert session.status == SessionStatus.RUNNING

    # Should have: session.started + session.message (system/init)
    types = [e["type"] for e in events]
    assert "session.started" in types
    assert "session.message" in types

    # The system/init message should contain model info
    init_events = [e for e in events if e["type"] == "session.message" and e["data"].get("subtype") == "init"]
    assert len(init_events) == 1
    assert init_events[0]["data"]["model"] == "mock-model"

    session.stop()


@pytest.mark.asyncio
async def test_session_send_and_stream_response(opts: SessionOptions) -> None:
    """Sending a message should produce stream_event and result events."""
    session = Session(opts, MockAdapter())
    events: list[dict] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    session.on_event(collect)
    await session.start()
    await asyncio.sleep(0.2)

    # Send a message
    await session.send("hello world")
    await asyncio.sleep(0.3)

    # Filter to session.message events with data
    messages = [e for e in events if e["type"] == "session.message"]
    data_types = [m["data"]["type"] for m in messages]

    # Should have system init, then stream_event, then result
    assert "system" in data_types
    assert "stream_event" in data_types
    assert "result" in data_types

    # The stream_event should contain our echoed text
    stream_events = [m for m in messages if m["data"]["type"] == "stream_event"]
    assert len(stream_events) >= 1
    delta = stream_events[0]["data"]["event"]["delta"]["text"]
    assert "hello world" in delta

    session.stop()


@pytest.mark.asyncio
async def test_session_stop_emits_exit(opts: SessionOptions) -> None:
    """Stopping a session should emit session.exit."""
    session = Session(opts, MockAdapter())
    events: list[dict] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    session.on_event(collect)
    await session.start()
    await asyncio.sleep(0.2)

    session.stop()
    # Wait for process to finish and emit exit
    await asyncio.sleep(0.5)

    exit_events = [e for e in events if e["type"] == "session.exit"]
    assert len(exit_events) == 1
    assert session.status == SessionStatus.STOPPED


@pytest.mark.asyncio
async def test_session_extracts_tool_session_id(opts: SessionOptions) -> None:
    """Session should capture session_id from system/init event."""
    session = Session(opts, MockAdapter())
    await session.start()
    await asyncio.sleep(0.3)

    assert session._tool_session_id == "mock-session-123"

    session.stop()


@pytest.mark.asyncio
async def test_session_multiple_messages(opts: SessionOptions) -> None:
    """Multiple sends should each produce responses."""
    session = Session(opts, MockAdapter())
    events: list[dict] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    session.on_event(collect)
    await session.start()
    await asyncio.sleep(0.2)

    await session.send("first")
    await asyncio.sleep(0.2)
    await session.send("second")
    await asyncio.sleep(0.2)

    results = [
        e for e in events
        if e["type"] == "session.message" and e["data"].get("type") == "result"
    ]
    assert len(results) == 2
    assert "first" in results[0]["data"]["text"]
    assert "second" in results[1]["data"]["text"]

    session.stop()


@pytest.mark.asyncio
async def test_session_callback_removal(opts: SessionOptions) -> None:
    """Removed callbacks should not receive further events."""
    session = Session(opts, MockAdapter())
    events: list[dict] = []

    async def collect(event: dict[str, Any]) -> None:
        events.append(event)

    session.on_event(collect)
    await session.start()
    await asyncio.sleep(0.2)

    session.remove_callback(collect)
    await session.send("after removal")
    await asyncio.sleep(0.2)

    # Events collected before removal should exist, but nothing after
    messages_after = [
        e for e in events
        if e["type"] == "session.message" and "after removal" in str(e.get("data", {}))
    ]
    assert len(messages_after) == 0

    session.stop()


@pytest.mark.asyncio
async def test_session_tilde_expansion() -> None:
    """work_dir with ~ should be expanded."""
    opts = SessionOptions(work_dir="~/nonexistent_test_dir_abc", tool="mock")
    session = Session(opts, MockAdapter())

    # start() expands the path — but the dir doesn't exist, so subprocess will still work
    # (mock_cli doesn't care about cwd). We just verify the expansion happened.
    try:
        await session.start()
        await asyncio.sleep(0.1)
    except Exception:
        pass

    assert "~" not in session.opts.work_dir
    assert session.opts.work_dir.startswith("/")

    session.stop()
