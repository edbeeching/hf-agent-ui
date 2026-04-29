from __future__ import annotations

import asyncio
import sys
from pathlib import Path

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
