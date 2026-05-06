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

EventCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

MAX_OUTPUT_BUFFER_BYTES = 1_000_000
TUI_PAUSE_EXIT_COMMAND = "/exit\r"
BASH_PAUSE_EXIT_COMMAND = "exit\r"
PAUSE_EXIT_GRACE_SECONDS = 5.0
CUSTOM_LAUNCH_SHELL_ENV = "HF_AGENT_UI_CUSTOM_LAUNCH_SHELL"

TOOL_COMMANDS: dict[str, list[str]] = {
    "bash": ["bash"],
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
    needs_input_kind: str | None
    needs_input_source: str | None
    needs_input_title: str | None
    needs_input_message: str | None
    needs_input_detected_at: str | None
    launch_mode: str
    launch_command: str | None
    launch_label: str | None


@dataclass(frozen=True)
class InputRequiredSignal:
    reason: str
    kind: str
    title: str
    message: str | None = None
    tool_name: str | None = None


class PtySession:
    """Wraps a CLI tool in a pseudo-terminal."""

    def __init__(
        self,
        work_dir: str,
        tool: str = "claude",
        cols: int = 120,
        rows: int = 40,
        session_id: str | None = None,
        created_at: str | None = None,
        status: str = "starting",
        resume_token: str | None = None,
        launch_mode: str = "local",
        launch_command: str | None = None,
        launch_label: str | None = None,
    ) -> None:
        self.id = session_id or str(uuid.uuid4())
        self.work_dir = str(Path(os.path.expanduser(work_dir)).resolve())
        self.tool = tool
        self.cols = cols
        self.rows = rows
        self.status = status
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.resume_token = resume_token
        self.launch_mode = _normalize_launch_mode(launch_mode)
        self.launch_command = _normalize_launch_command(self.launch_mode, launch_command)
        self.launch_label = _normalize_launch_label(self.launch_mode, launch_label)
        self.needs_input = False
        self.needs_input_reason: str | None = None
        self.needs_input_kind: str | None = None
        self.needs_input_source: str | None = None
        self.needs_input_title: str | None = None
        self.needs_input_message: str | None = None
        self.needs_input_detected_at: str | None = None
        self._master_fd: int | None = None
        self._proc: subprocess.Popen | None = None
        self._read_task: asyncio.Task | None = None
        self._hook_task: asyncio.Task | None = None
        self._pause_fallback_task: asyncio.Task | None = None
        self._callbacks: list[EventCallback] = []
        self._recent_output = ""
        self._output_buffer: list[str] = []
        self._output_buffer_bytes = 0
        self._exit_status = "stopped"
        self._codex_hook_enabled = False

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
        await self._spawn(resume=False)

    async def resume(self) -> None:
        if self.status == "running":
            return
        await self._finish_pending_pause()
        await self._spawn(resume=True)

    async def _spawn(self, *, resume: bool) -> None:
        cmd = TOOL_COMMANDS.get(self.tool)
        if not cmd:
            raise ValueError(f"Unknown tool: {self.tool}. Available: {list(TOOL_COMMANDS.keys())}")

        master_fd, slave_fd = pty.openpty()

        # Set terminal size
        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        hook_file: Path | None = None
        if self.tool == "claude":
            hook_file = self._prepare_claude_notification_hook(env)
        elif self.tool == "codex":
            hook_file = self._prepare_codex_permission_hook(env)
        args = self._build_args(cmd, resume=resume)

        self._proc = subprocess.Popen(
            args,
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
        if self._pause_fallback_task:
            self._pause_fallback_task.cancel()
            self._pause_fallback_task = None
        logger.info("PTY session %s started (pid=%d, tool=%s)", self.id, self._proc.pid, self.tool)
        await self._emit({"type": "pty.started", "sessionId": self.id})

        if hook_file and self.tool == "claude":
            self._hook_task = asyncio.create_task(self._watch_claude_notifications(hook_file))
        elif hook_file and self.tool == "codex":
            self._hook_task = asyncio.create_task(self._watch_codex_permission_requests(hook_file))
        self._read_task = asyncio.create_task(self._read_loop())

    def _build_args(self, cmd: list[str], *, resume: bool) -> list[str]:
        args = self._build_tool_args(cmd, resume=resume)
        if self.launch_mode == "custom":
            return [os.environ.get(CUSTOM_LAUNCH_SHELL_ENV, "/bin/sh"), "-lc", self._render_launch_command(args)]
        return args

    def _build_tool_args(self, cmd: list[str], *, resume: bool) -> list[str]:
        args = list(cmd)
        if self.tool == "claude":
            if resume and self.resume_token:
                args.extend(["--resume", self.resume_token])
            elif not resume:
                self.resume_token = self.resume_token or str(uuid.uuid4())
                args.extend(["--session-id", self.resume_token])
        elif self.tool == "codex":
            if self._codex_hook_enabled:
                args.extend(_codex_hook_config_args())
            args.extend(["--cd", self.work_dir])
            if resume:
                args.append("resume")
                if self.resume_token:
                    args.append(self.resume_token)
                else:
                    args.append("--last")
        return args

    def _render_launch_command(self, tool_args: list[str]) -> str:
        if not self.launch_command or "{command}" not in self.launch_command:
            raise ValueError("Custom launch command must include {command}")
        return (
            self.launch_command
            .replace("{command}", shlex.join(tool_args))
            .replace("{workDir}", shlex.quote(self.work_dir))
        )

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
                        self._append_output(text)
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
            if self.tool == "codex" and not self.resume_token:
                self.resume_token = self._latest_codex_session_id()
            code = self._proc.returncode if self._proc else -1
            if self._proc and code is None:
                code = self._proc.wait()
            self.status = self._exit_status
            self._exit_status = "stopped"
            self._close_master_fd()
            if self._pause_fallback_task:
                self._pause_fallback_task.cancel()
                self._pause_fallback_task = None
            logger.info("PTY process exited with code %s", code)
            await self._mark_input_resolved()
            await self._emit({
                "type": "pty.exit",
                "sessionId": self.id,
                "code": code,
                "status": self.status,
            })

    def _latest_codex_session_id(self) -> str | None:
        sessions_dir = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "sessions"
        matches: list[tuple[float, str]] = []
        for path in sessions_dir.glob("**/*.jsonl"):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    line = fh.readline()
                record = json.loads(line)
                if record.get("type") != "session_meta":
                    continue
                payload = record.get("payload") or {}
                if Path(payload.get("cwd", "")).resolve() != Path(self.work_dir).resolve():
                    continue
                session_id = payload.get("id")
                if isinstance(session_id, str):
                    matches.append((path.stat().st_mtime, session_id))
            except (OSError, json.JSONDecodeError, RuntimeError):
                continue
        if not matches:
            return None
        return max(matches, key=lambda item: item[0])[1]

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
        if self._pause_fallback_task:
            self._pause_fallback_task.cancel()
            self._pause_fallback_task = None
        if self._proc and self._proc.poll() is None:
            self._exit_status = "stopped"
            self._terminate_process()
            self.status = "stopped"
            if self.needs_input:
                self._schedule_input_resolved()
        self._close_master_fd()

    def pause(self) -> None:
        if self.tool == "codex" and not self.resume_token:
            self.resume_token = self._latest_codex_session_id()
        if self._proc and self.status == "running":
            self._exit_status = "paused"
            self.status = "paused"
            if self.needs_input:
                self._schedule_input_resolved()
            if self._request_tui_exit():
                self._schedule_pause_fallback()
                return
            self._terminate_process()
        self.status = "paused"
        if self.needs_input:
            self._schedule_input_resolved()
        self._close_master_fd()

    def _request_tui_exit(self) -> bool:
        if self._master_fd is None:
            return False
        try:
            os.write(self._master_fd, self._pause_exit_command().encode("utf-8"))
            return True
        except OSError:
            return False

    def _pause_exit_command(self) -> str:
        if self.tool == "bash":
            return BASH_PAUSE_EXIT_COMMAND
        return TUI_PAUSE_EXIT_COMMAND

    def _terminate_process(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                try:
                    os.kill(self._proc.pid, signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass

    def _close_master_fd(self) -> None:
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

    def _schedule_pause_fallback(self) -> None:
        if not self._proc or self._proc.poll() is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._pause_fallback_task:
            self._pause_fallback_task.cancel()
        proc = self._proc
        self._pause_fallback_task = loop.create_task(self._terminate_if_pause_hangs(proc))

    async def _terminate_if_pause_hangs(self, proc: subprocess.Popen) -> None:
        await asyncio.sleep(PAUSE_EXIT_GRACE_SECONDS)
        if self._proc is proc and proc.poll() is None and self.status == "paused":
            logger.warning("PTY session %s did not exit after /exit; terminating", self.id)
            self._terminate_process()

    async def _finish_pending_pause(self) -> None:
        if not self._proc or self._proc.poll() is not None:
            return
        if self.status != "paused":
            return
        try:
            await asyncio.wait_for(asyncio.to_thread(self._proc.wait), timeout=PAUSE_EXIT_GRACE_SECONDS)
        except TimeoutError:
            logger.warning("PTY session %s still running during resume; terminating before restart", self.id)
            self._terminate_process()
            await asyncio.to_thread(self._proc.wait)

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
            needs_input_kind=self.needs_input_kind,
            needs_input_source=self.needs_input_source,
            needs_input_title=self.needs_input_title,
            needs_input_message=self.needs_input_message,
            needs_input_detected_at=self.needs_input_detected_at,
            launch_mode=self.launch_mode,
            launch_command=self.launch_command,
            launch_label=self.launch_label,
        )

    def get_output_buffer(self) -> list[str]:
        return list(self._output_buffer)

    def to_record(self) -> dict[str, Any]:
        return {
            "kind": "pty",
            "id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "work_dir": self.work_dir,
            "tool": self.tool,
            "cols": self.cols,
            "rows": self.rows,
            "resume_token": self.resume_token,
            "launch_mode": self.launch_mode,
            "launch_command": self.launch_command,
            "launch_label": self.launch_label,
        }

    def _append_output(self, text: str) -> None:
        size = len(text.encode("utf-8", errors="replace"))
        self._output_buffer.append(text)
        self._output_buffer_bytes += size
        while self._output_buffer_bytes > MAX_OUTPUT_BUFFER_BYTES and self._output_buffer:
            removed = self._output_buffer.pop(0)
            self._output_buffer_bytes -= len(removed.encode("utf-8", errors="replace"))

    async def _mark_input_required(self, signal: InputRequiredSignal, source: str) -> None:
        reason = signal.reason.strip() or "Human input required"
        kind = _normalize_input_kind(signal.kind)
        title = signal.title.strip() or _title_for_input_kind(kind)
        message = signal.message.strip() if signal.message else reason
        source = source.strip() or "pty"
        if (
            self.needs_input
            and self.needs_input_reason == reason
            and self.needs_input_kind == kind
            and self.needs_input_source == source
        ):
            return
        detected_at = datetime.now(timezone.utc).isoformat()
        self.needs_input = True
        self.needs_input_reason = reason
        self.needs_input_kind = kind
        self.needs_input_source = source
        self.needs_input_title = title
        self.needs_input_message = message
        self.needs_input_detected_at = detected_at
        event: dict[str, Any] = {
            "type": "session.input_required",
            "sessionId": self.id,
            "reason": reason,
            "source": source,
            "kind": kind,
            "title": title,
            "message": message,
            "detectedAt": detected_at,
        }
        if signal.tool_name:
            event["toolName"] = signal.tool_name
        await self._emit(event)

    async def _mark_input_resolved(self) -> None:
        if not self.needs_input:
            return
        self.needs_input = False
        self.needs_input_reason = None
        self.needs_input_kind = None
        self.needs_input_source = None
        self.needs_input_title = None
        self.needs_input_message = None
        self.needs_input_detected_at = None
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
        signal = _detect_action_required(self._recent_output, self.tool)
        if signal:
            await self._mark_input_required(signal, "pty")

    def _prepare_claude_notification_hook(self, env: dict[str, str]) -> Path | None:
        hook_dir = Path(tempfile.gettempdir()) / "hf-agent-ui-claude-hooks"
        hook_dir.mkdir(parents=True, exist_ok=True)
        hook_file = hook_dir / f"{self.id}.jsonl"
        hook_file.touch(exist_ok=True)

        env["HF_AGENT_UI_PTY_SESSION_ID"] = self.id
        env["HF_AGENT_UI_CLAUDE_HOOK_DIR"] = str(hook_dir)
        env["HF_AGENT_UI_PYTHON"] = sys.executable

        try:
            self._install_claude_notification_hook()
        except Exception:
            logger.exception("Failed to install Claude notification hook for session %s", self.id)
        return hook_file

    def _prepare_codex_permission_hook(self, env: dict[str, str]) -> Path | None:
        hook_dir = Path(tempfile.gettempdir()) / "hf-agent-ui-codex-hooks"
        hook_dir.mkdir(parents=True, exist_ok=True)
        hook_file = hook_dir / f"{self.id}.jsonl"
        hook_file.touch(exist_ok=True)

        env["HF_AGENT_UI_PTY_SESSION_ID"] = self.id
        env["HF_AGENT_UI_CODEX_HOOK_DIR"] = str(hook_dir)
        env["HF_AGENT_UI_PYTHON"] = sys.executable
        self._codex_hook_enabled = True
        return hook_file

    def _install_claude_notification_hook(self) -> None:
        work_dir = Path(self.work_dir)
        if not work_dir.is_dir():
            logger.warning("Skipping Claude hook install because work directory does not exist: %s", work_dir)
            return
        settings_dir = work_dir / ".claude"
        settings_file = settings_dir / "settings.local.json"
        command = f"{shlex.quote(sys.executable)} -m hf_agent_ui.daemon.claude_hook"

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
                            signal = _detect_claude_notification(event)
                            if signal:
                                await self._mark_input_required(signal, "claude-hook")
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to read Claude notification hook output")
                await asyncio.sleep(1.0)

    async def _watch_codex_permission_requests(self, hook_file: Path) -> None:
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
                            if event.get("hook_event_name") != "PermissionRequest":
                                continue
                            signal = _detect_codex_permission_request(event)
                            if signal:
                                await self._mark_input_required(signal, "codex-hook")
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to read Codex permission hook output")
                await asyncio.sleep(1.0)


ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07]*(?:\x07|\x1b\\)"
    r"|\x1b[()][A-Za-z0-9]"
)


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "\n")


def _detect_claude_notification(event: dict[str, Any]) -> InputRequiredSignal | None:
    message = str(event.get("message", "")).strip()
    notification_type = str(event.get("notification_type", "")).strip()
    title = str(event.get("title", "")).strip()

    if notification_type == "permission_prompt":
        return InputRequiredSignal(
            reason=message or "Claude permission required",
            kind="permission",
            title=title or "Claude permission required",
            message=message or None,
            tool_name="claude",
        )
    if notification_type == "idle_prompt":
        return InputRequiredSignal(
            reason=message or "Claude is waiting for input",
            kind="prompt",
            title=title or "Claude waiting",
            message=message or None,
            tool_name="claude",
        )
    if notification_type == "elicitation_dialog":
        return InputRequiredSignal(
            reason=message or "Claude needs input from an MCP dialog",
            kind="prompt",
            title=title or "Claude input requested",
            message=message or None,
            tool_name="claude",
        )

    lower = message.lower()
    if "permission" in lower or "needs your" in lower:
        return InputRequiredSignal(
            reason=message or "Claude permission required",
            kind="permission",
            title=title or "Claude permission required",
            message=message or None,
            tool_name="claude",
        )
    if "waiting for your input" in lower:
        return InputRequiredSignal(
            reason=message or "Claude is waiting for input",
            kind="prompt",
            title=title or "Claude waiting",
            message=message or None,
            tool_name="claude",
        )
    return None


def _detect_codex_permission_request(event: dict[str, Any]) -> InputRequiredSignal | None:
    tool_name = str(event.get("tool_name", "")).strip() or "tool"
    tool_input = event.get("tool_input")
    description = None
    command = None
    if isinstance(tool_input, dict):
        raw_description = tool_input.get("description")
        raw_command = tool_input.get("command")
        if isinstance(raw_description, str) and raw_description.strip():
            description = raw_description.strip()
        if isinstance(raw_command, str) and raw_command.strip():
            command = raw_command.strip()

    if description:
        reason = description
        message = description
    elif command:
        reason = "Codex command approval required"
        message = f"Codex wants to run: {command}"
    else:
        reason = f"Codex needs approval for {tool_name}"
        message = reason

    return InputRequiredSignal(
        reason=reason,
        kind="permission",
        title="Codex approval required",
        message=message,
        tool_name=tool_name,
    )


def _detect_action_required(output: str, tool: str) -> InputRequiredSignal | None:
    text = " ".join(output.lower().split())

    common_patterns = [
        (r"\bneeds your permission\b", InputRequiredSignal("Permission required", "permission", "Permission required")),
        (r"\bwaiting for your input\b", InputRequiredSignal("Waiting for input", "prompt", "Input needed")),
        (r"\bdo you want to\b", InputRequiredSignal("Confirmation required", "confirmation", "Confirmation required")),
        (r"\bpress enter to continue\b", InputRequiredSignal("Waiting for Enter", "prompt", "Input needed")),
        (r"\b(sign in|log in|login|authenticate)\b", InputRequiredSignal("Authentication required", "auth", "Authentication required")),
        (r"\b(approve|approval required)\b", InputRequiredSignal("Approval required", "permission", "Approval required")),
        (r"\b(allow|deny)\b.*\?", InputRequiredSignal("Permission required", "permission", "Permission required")),
        (r"\b(y/n|yes/no)\b", InputRequiredSignal("Confirmation required", "confirmation", "Confirmation required")),
    ]

    codex_patterns = [
        (r"\bapprove\b.*\b(command|edit|patch|change)\b", InputRequiredSignal("Codex approval required", "permission", "Codex approval required")),
        (r"\brun command\b.*\?", InputRequiredSignal("Codex command approval required", "permission", "Codex approval required")),
        (r"\bapply\b.*\bpatch\b.*\?", InputRequiredSignal("Codex edit approval required", "permission", "Codex approval required")),
    ]

    claude_patterns = [
        (r"\bclaude needs your permission\b", InputRequiredSignal("Claude permission required", "permission", "Claude permission required")),
        (r"\bpermission to use\b", InputRequiredSignal("Claude permission required", "permission", "Claude permission required")),
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


def _normalize_input_kind(kind: str) -> str:
    if kind in {"permission", "confirmation", "auth", "prompt"}:
        return kind
    return "prompt"


def _title_for_input_kind(kind: str) -> str:
    if kind == "permission":
        return "Permission required"
    if kind == "confirmation":
        return "Confirmation required"
    if kind == "auth":
        return "Authentication required"
    return "Input needed"


def _codex_hook_config_args() -> list[str]:
    command = shlex.join([sys.executable, "-m", "hf_agent_ui.daemon.codex_hook"])
    hook_config = (
        "hooks.PermissionRequest=[{"
        'matcher="", hooks=[{'
        'type="command", '
        f"command={json.dumps(command)}, "
        "timeout=5, "
        'statusMessage="Notifying hf-agent-ui"'
        "}]"
        "}]"
    )
    return [
        "-c",
        "features.codex_hooks=true",
        "-c",
        hook_config,
    ]


def _normalize_launch_mode(value: object) -> str:
    if value is None:
        return "local"
    if value not in {"local", "custom"}:
        raise ValueError(f"Unknown launch mode: {value}")
    return str(value)


def _normalize_launch_command(launch_mode: str, value: object) -> str | None:
    if launch_mode != "custom":
        return None
    command = value.strip() if isinstance(value, str) else ""
    if "{command}" not in command:
        raise ValueError("Custom launch command must include {command}")
    return command


def _normalize_launch_label(launch_mode: str, value: object) -> str | None:
    if launch_mode != "custom":
        return None
    label = value.strip() if isinstance(value, str) else ""
    return label or "custom"
