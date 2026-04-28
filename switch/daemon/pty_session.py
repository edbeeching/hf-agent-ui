"""PTY-based session — spawns CLI tools in a pseudo-terminal.

Streams raw terminal output (ANSI codes and all) instead of parsed JSON.
This gives the full TUI experience for any CLI tool.
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import signal
import struct
import subprocess
import termios
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

type EventCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

TOOL_COMMANDS: dict[str, list[str]] = {
    "claude": ["claude"],
    "codex": ["codex"],
}


@dataclass
class PtySessionInfo:
    id: str
    status: str
    work_dir: str
    tool: str
    mode: str
    created_at: str


class PtySession:
    """Wraps a CLI tool in a pseudo-terminal."""

    def __init__(
        self,
        work_dir: str,
        tool: str = "claude",
        cols: int = 120,
        rows: int = 40,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.work_dir = os.path.expanduser(work_dir)
        self.tool = tool
        self.cols = cols
        self.rows = rows
        self.status = "starting"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self._master_fd: int | None = None
        self._proc: subprocess.Popen | None = None
        self._read_task: asyncio.Task | None = None
        self._callbacks: list[EventCallback] = []

    def on_event(self, cb: EventCallback) -> None:
        self._callbacks.append(cb)

    def remove_callback(self, cb: EventCallback) -> None:
        self._callbacks = [c for c in self._callbacks if c is not cb]

    async def _emit(self, event: dict[str, Any]) -> None:
        for cb in self._callbacks:
            try:
                await cb(event)
            except Exception:
                logger.exception("Error in PTY session event callback")

    async def start(self) -> None:
        cmd = TOOL_COMMANDS.get(self.tool)
        if not cmd:
            raise ValueError(f"Unknown tool: {self.tool}. Available: {list(TOOL_COMMANDS.keys())}")

        master_fd, slave_fd = pty.openpty()

        # Set terminal size
        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"

        self._proc = subprocess.Popen(
            cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=self.work_dir,
            env=env,
            start_new_session=True,
        )
        os.close(slave_fd)
        self._master_fd = master_fd

        # Make non-blocking
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self.status = "running"
        logger.info("PTY session %s started (pid=%d, tool=%s)", self.id, self._proc.pid, self.tool)
        await self._emit({"type": "pty.started", "sessionId": self.id})

        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._master_fd is not None
        loop = asyncio.get_running_loop()

        try:
            while self._proc and self._proc.poll() is None:
                try:
                    data = await asyncio.wait_for(
                        loop.run_in_executor(None, self._blocking_read),
                        timeout=1.0,
                    )
                    if data:
                        await self._emit({
                            "type": "pty.output",
                            "sessionId": self.id,
                            "data": data.decode("utf-8", errors="replace"),
                        })
                except TimeoutError:
                    continue
                except OSError:
                    break
        finally:
            code = self._proc.returncode if self._proc else -1
            if self._proc and code is None:
                code = self._proc.wait()
            self.status = "stopped"
            logger.info("PTY process exited with code %s", code)
            await self._emit({
                "type": "pty.exit",
                "sessionId": self.id,
                "code": code,
            })

    def _blocking_read(self) -> bytes:
        """Blocking read with select timeout. Runs in thread executor."""
        import select
        assert self._master_fd is not None
        r, _, _ = select.select([self._master_fd], [], [], 0.5)
        if r:
            return os.read(self._master_fd, 16384)
        return b""

    def write(self, data: str) -> None:
        """Write input (keystrokes) to the PTY."""
        if self._master_fd is not None and self.status == "running":
            os.write(self._master_fd, data.encode("utf-8"))

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY terminal."""
        if self._master_fd is not None:
            self.cols = cols
            self.rows = rows
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    def stop(self) -> None:
        if self._proc and self.status == "running":
            try:
                os.kill(self._proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            self.status = "stopped"
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

    def to_info(self) -> PtySessionInfo:
        return PtySessionInfo(
            id=self.id,
            status=self.status,
            work_dir=self.work_dir,
            tool=self.tool,
            mode="pty",
            created_at=self.created_at,
        )
