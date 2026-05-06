from __future__ import annotations

import asyncio
import os
import shlex
import signal
import sys
from pathlib import Path

import pytest

from switch.daemon.pty_session import TOOL_COMMANDS, PtySession


MOCK_CLI = str(Path(__file__).parent / "mock_cli.py")


def test_pause_exits_tui_cleanly_and_keeps_session_paused(tmp_path: Path) -> None:
    async def run() -> None:
        session = PtySession(work_dir=str(tmp_path), tool="mock")
        await session.start()

        session.pause()

        assert session._read_task is not None
        await asyncio.wait_for(session._read_task, timeout=2)
        assert session.status == "paused"
        assert session._proc is not None
        assert session._proc.returncode == 0
        assert session._master_fd is None

    TOOL_COMMANDS["mock"] = [sys.executable, MOCK_CLI]
    try:
        asyncio.run(run())
    finally:
        del TOOL_COMMANDS["mock"]


def test_custom_launch_command_renders_quoted_placeholders(tmp_path: Path) -> None:
    work_dir = tmp_path / "project with spaces"
    work_dir.mkdir()
    tool_args = ["/bin/mock tool", "arg value"]
    session = PtySession(
        work_dir=str(work_dir),
        tool="mock",
        launch_mode="custom",
        launch_command="launcher --cwd {workDir} -- {command}",
        launch_label="gpu",
    )

    args = session._build_args(tool_args, resume=False)

    assert args[:2] == ["/bin/sh", "-lc"]
    assert args[2] == (
        f"launcher --cwd {shlex.quote(str(work_dir.resolve()))} -- "
        f"{shlex.join(tool_args)}"
    )
    assert session.to_info().launch_mode == "custom"
    assert session.to_info().launch_label == "gpu"


def test_custom_launch_command_requires_command_placeholder(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\{command\}"):
        PtySession(
            work_dir=str(tmp_path),
            tool="mock",
            launch_mode="custom",
            launch_command="launcher --cwd {workDir}",
        )


def test_custom_launch_resume_uses_same_template(tmp_path: Path) -> None:
    session = PtySession(
        work_dir=str(tmp_path),
        tool="claude",
        launch_mode="custom",
        launch_command="launcher {command}",
        resume_token="claude-session",
    )

    args = session._build_args(["claude"], resume=True)

    assert args[2] == "launcher claude --resume claude-session"


def test_bash_tool_builds_plain_shell_command(tmp_path: Path) -> None:
    session = PtySession(work_dir=str(tmp_path), tool="bash")

    assert TOOL_COMMANDS["bash"] == ["bash"]
    assert session._build_tool_args(["bash"], resume=False) == ["bash"]
    assert session._build_tool_args(["bash"], resume=True) == ["bash"]
    assert session._pause_exit_command() == "exit\r"


def test_terminate_process_targets_process_group(monkeypatch, tmp_path: Path) -> None:
    class FakeProc:
        pid = 123

        def poll(self):
            return None

    calls = []
    session = PtySession(work_dir=str(tmp_path), tool="mock")
    session._proc = FakeProc()

    monkeypatch.setattr(os, "getpgid", lambda pid: 456)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))

    session._terminate_process()

    assert calls == [(456, signal.SIGTERM)]
