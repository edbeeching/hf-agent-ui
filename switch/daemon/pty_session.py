"""PTY-based session — spawns CLI tools in a pseudo-terminal.

Streams raw terminal output (ANSI codes and all) instead of parsed JSON.
This gives the full TUI experience for any CLI tool.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import re
import signal
import shlex
import struct
import subprocess
import sys
import termios
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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
    needs_input: bool
    needs_input_reason: str | None


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
        self.needs_input = False
        self.needs_input_reason: str | None = None
        self._master_fd: int | None = None
        self._proc: subprocess.Popen | None = None
        self._read_task: asyncio.Task | None = None
        self._hook_task: asyncio.Task | None = None
        self._callbacks: list[EventCallback] = []
        self._recent_output = ""

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
        hook_file = self._prepare_claude_notification_hook(env) if self.tool == "claude" else None

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

        if hook_file:
            self._hook_task = asyncio.create_task(self._watch_claude_notifications(hook_file))
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
                        text = data.decode("utf-8", errors="replace")
                        await self._emit({
                            "type": "pty.output",
                            "sessionId": self.id,
                            "data": text,
                        })
                        await self._detect_input_required_from_output(text)
                except TimeoutError:
                    continue
                except OSError:
                    break
        finally:
            if self._hook_task:
                self._hook_task.cancel()
            code = self._proc.returncode if self._proc else -1
            if self._proc and code is None:
                code = self._proc.wait()
            self.status = "stopped"
            logger.info("PTY process exited with code %s", code)
            await self._mark_input_resolved()
            await self._emit({
                "type": "pty.exit",
                "sessionId": self.id,
                "code": code,
            })

    def _blocking_read(self) -> bytes:
        """Blocking read with select timeout. Runs in thread executor."""
        import select
        master_fd = self._master_fd
        if master_fd is None:
            return b""
        r, _, _ = select.select([master_fd], [], [], 0.5)
        if r:
            return os.read(master_fd, 16384)
        return b""

    def write(self, data: str) -> None:
        """Write input (keystrokes) to the PTY."""
        if self._master_fd is not None and self.status == "running":
            os.write(self._master_fd, data.encode("utf-8"))
            if data and self.needs_input:
                self._schedule_input_resolved()

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
            if self.needs_input:
                self._schedule_input_resolved()
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
            needs_input=self.needs_input,
            needs_input_reason=self.needs_input_reason,
        )

    async def _mark_input_required(self, reason: str, source: str) -> None:
        reason = reason.strip() or "Human input required"
        if self.needs_input and self.needs_input_reason == reason:
            return
        self.needs_input = True
        self.needs_input_reason = reason
        await self._emit({
            "type": "session.input_required",
            "sessionId": self.id,
            "reason": reason,
            "source": source,
        })

    async def _mark_input_resolved(self) -> None:
        if not self.needs_input:
            return
        self.needs_input = False
        self.needs_input_reason = None
        self._recent_output = ""
        await self._emit({
            "type": "session.input_resolved",
            "sessionId": self.id,
        })

    def _schedule_input_resolved(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._mark_input_resolved())

    async def _detect_input_required_from_output(self, text: str) -> None:
        clean = _strip_ansi(text)
        if not clean.strip():
            return
        self._recent_output = (self._recent_output + clean)[-4000:]
        reason = _detect_action_required(self._recent_output, self.tool)
        if reason:
            await self._mark_input_required(reason, "pty")

    def _prepare_claude_notification_hook(self, env: dict[str, str]) -> Path | None:
        hook_dir = Path(tempfile.gettempdir()) / "switch-claude-hooks"
        hook_dir.mkdir(parents=True, exist_ok=True)
        hook_file = hook_dir / f"{self.id}.jsonl"
        hook_file.touch(exist_ok=True)

        env["SWITCH_PTY_SESSION_ID"] = self.id
        env["SWITCH_CLAUDE_HOOK_DIR"] = str(hook_dir)
        env["SWITCH_PYTHON"] = sys.executable

        try:
            self._install_claude_notification_hook()
        except Exception:
            logger.exception("Failed to install Claude notification hook for session %s", self.id)
        return hook_file

    def _install_claude_notification_hook(self) -> None:
        work_dir = Path(self.work_dir)
        if not work_dir.is_dir():
            logger.warning("Skipping Claude hook install because work directory does not exist: %s", work_dir)
            return
        settings_dir = work_dir / ".claude"
        settings_file = settings_dir / "settings.local.json"
        command = f"{shlex.quote(sys.executable)} -m switch.daemon.claude_hook"

        settings: dict[str, Any] = {}
        if settings_file.exists():
            try:
                loaded = json.loads(settings_file.read_text())
            except json.JSONDecodeError:
                logger.warning("Skipping Claude hook install because %s is not valid JSON", settings_file)
                return
            if not isinstance(loaded, dict):
                logger.warning("Skipping Claude hook install because %s is not a JSON object", settings_file)
                return
            settings = loaded

        hooks = settings.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            logger.warning("Skipping Claude hook install because hooks in %s is not an object", settings_file)
            return
        notifications = hooks.setdefault("Notification", [])
        if not isinstance(notifications, list):
            logger.warning("Skipping Claude hook install because Notification hooks in %s is not a list", settings_file)
            return

        for group in notifications:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks", []):
                if isinstance(hook, dict) and hook.get("type") == "command" and hook.get("command") == command:
                    return

        notifications.append({
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                },
            ],
        })
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")

    async def _watch_claude_notifications(self, hook_file: Path) -> None:
        offset = 0
        while self._proc and self._proc.poll() is None:
            try:
                if hook_file.exists():
                    with hook_file.open() as f:
                        f.seek(offset)
                        while line := f.readline():
                            offset = f.tell()
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if event.get("hook_event_name") != "Notification":
                                continue
                            message = str(event.get("message", ""))
                            reason = _detect_claude_notification(message)
                            if reason:
                                await self._mark_input_required(reason, "claude-hook")
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to read Claude notification hook output")
                await asyncio.sleep(1.0)


ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07]*(?:\x07|\x1b\\)"
    r"|\x1b[()][A-Za-z0-9]"
)


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "\n")


def _detect_claude_notification(message: str) -> str | None:
    lower = message.lower()
    if "permission" in lower or "waiting for your input" in lower or "needs your" in lower:
        return message
    return None


def _detect_action_required(output: str, tool: str) -> str | None:
    text = " ".join(output.lower().split())

    common_patterns = [
        (r"\bneeds your permission\b", "Permission required"),
        (r"\bwaiting for your input\b", "Waiting for input"),
        (r"\bdo you want to\b", "Confirmation required"),
        (r"\bpress enter to continue\b", "Waiting for Enter"),
        (r"\b(sign in|log in|login|authenticate)\b", "Authentication required"),
        (r"\b(approve|approval required)\b", "Approval required"),
        (r"\b(allow|deny)\b.*\?", "Permission required"),
        (r"\b(y/n|yes/no)\b", "Confirmation required"),
    ]

    codex_patterns = [
        (r"\bapprove\b.*\b(command|edit|patch|change)\b", "Codex approval required"),
        (r"\brun command\b.*\?", "Codex command approval required"),
        (r"\bapply\b.*\bpatch\b.*\?", "Codex edit approval required"),
    ]

    claude_patterns = [
        (r"\bclaude needs your permission\b", "Claude permission required"),
        (r"\bpermission to use\b", "Claude permission required"),
    ]

    patterns = common_patterns
    if tool == "codex":
        patterns = codex_patterns + patterns
    elif tool == "claude":
        patterns = claude_patterns + patterns

    for pattern, reason in patterns:
        if re.search(pattern, text):
            return reason
    return None
