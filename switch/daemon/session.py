from __future__ import annotations

import asyncio
import json
import logging
import signal
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from .adapters import ToolAdapter

logger = logging.getLogger(__name__)

type EventCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class SessionStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class SessionInfo:
    id: str
    status: SessionStatus
    work_dir: str
    model: str | None
    tool: str
    created_at: str


@dataclass
class SessionOptions:
    work_dir: str
    tool: str = "claude"
    model: str | None = None
    permission_mode: str | None = None
    allowed_tools: list[str] | None = None
    system_prompt: str | None = None
    initial_prompt: str | None = None


class Session:
    """Wraps an AI coding CLI process using a ToolAdapter for tool-specific behavior."""

    def __init__(self, opts: SessionOptions, adapter: ToolAdapter) -> None:
        self.id = str(uuid.uuid4())
        self.opts = opts
        self.adapter = adapter
        self.status = SessionStatus.STARTING
        self.created_at = datetime.now(timezone.utc).isoformat()
        self._proc: asyncio.subprocess.Process | None = None
        self._read_task: asyncio.Task | None = None
        self._callbacks: list[EventCallback] = []
        # For tools that use resume-based follow-ups (e.g. Codex)
        self._tool_session_id: str | None = None

    def on_event(self, cb: EventCallback) -> None:
        self._callbacks.append(cb)

    def remove_callback(self, cb: EventCallback) -> None:
        self._callbacks = [c for c in self._callbacks if c is not cb]

    async def _emit(self, event: dict[str, Any]) -> None:
        for cb in self._callbacks:
            try:
                await cb(event)
            except Exception:
                logger.exception("Error in session event callback")

    async def start(self) -> None:
        # Expand ~ and env vars in work_dir
        self.opts.work_dir = str(Path(self.opts.work_dir).expanduser().resolve())
        args = self.adapter.build_start_args(self.opts, self.opts.initial_prompt)
        await self._spawn(args)

    async def _spawn(self, args: list[str]) -> None:
        """Spawn a subprocess with the given args and start reading output."""
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.opts.work_dir if self.adapter.name != "codex" else None,
        )

        self.status = SessionStatus.RUNNING
        await self._emit({"type": "session.started", "sessionId": self.id})

        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout and self._proc.stderr

        async def read_stderr() -> None:
            assert self._proc and self._proc.stderr
            async for line in self._proc.stderr:
                text = line.decode().rstrip("\n")
                if text:
                    await self._emit({
                        "type": "session.stderr",
                        "sessionId": self.id,
                        "text": text,
                    })

        stderr_task = asyncio.create_task(read_stderr())

        try:
            async for line in self._proc.stdout:
                text = line.decode().rstrip("\n")
                if not text:
                    continue

                msg = self.adapter.parse_output_line(text)
                if msg is None:
                    continue

                # Try to extract the tool's internal session ID for resume support
                self._extract_tool_session_id(msg)

                await self._emit({
                    "type": "session.message",
                    "sessionId": self.id,
                    "data": msg,
                })
        finally:
            stderr_task.cancel()
            return_code = await self._proc.wait()
            self.status = SessionStatus.STOPPED
            await self._emit({
                "type": "session.exit",
                "sessionId": self.id,
                "code": return_code,
            })

    def _extract_tool_session_id(self, msg: dict[str, Any]) -> None:
        """Extract the tool's internal session ID from events, used for resume."""
        # Codex: thread.started event contains session_id
        if msg.get("type") == "thread.started" and msg.get("session_id"):
            self._tool_session_id = msg["session_id"]
        # Claude: system/init event may contain session_id
        if msg.get("type") == "system" and msg.get("session_id"):
            self._tool_session_id = msg["session_id"]

    async def send(self, message: str) -> None:
        if self.adapter.supports_stdin_messages():
            # Tools like Claude: write to stdin
            if not self._proc or not self._proc.stdin:
                raise RuntimeError(f"Session {self.id} is not writable (status: {self.status})")
            payload = self.adapter.format_user_message(message)
            if payload:
                self._proc.stdin.write((payload + "\n").encode())
                await self._proc.stdin.drain()
        else:
            # Tools like Codex: resume via new subprocess
            await self._resume_with_message(message)

    async def _resume_with_message(self, message: str) -> None:
        """For tools that don't support stdin messages, spawn a new process to resume."""
        if not self._tool_session_id:
            raise RuntimeError(
                f"Session {self.id}: cannot resume — no tool session ID captured yet. "
                "The initial prompt may still be running."
            )

        # Wait for current process to finish
        if self._proc and self._proc.returncode is None:
            # Process is still running — wait for it
            await self._emit({
                "type": "session.message",
                "sessionId": self.id,
                "data": {"type": "system", "text": "Waiting for current turn to complete before sending follow-up..."},
            })
            if self._read_task:
                await self._read_task
            await self._proc.wait()

        args = self.adapter.build_resume_args(self._tool_session_id, message, self.opts)
        await self._spawn(args)

    async def send_control(self, response: dict[str, Any]) -> None:
        payload = self.adapter.format_control_response(response)
        if payload is None:
            logger.warning("Tool %s does not support control responses", self.adapter.name)
            return
        if not self._proc or not self._proc.stdin:
            raise RuntimeError(f"Session {self.id} is not writable (status: {self.status})")
        self._proc.stdin.write((payload + "\n").encode())
        await self._proc.stdin.drain()

    def stop(self) -> None:
        if self._proc and self.status == SessionStatus.RUNNING:
            self._proc.send_signal(signal.SIGTERM)
            self.status = SessionStatus.STOPPED

    def to_info(self) -> SessionInfo:
        return SessionInfo(
            id=self.id,
            status=self.status,
            work_dir=self.opts.work_dir,
            model=self.opts.model,
            tool=self.opts.tool,
            created_at=self.created_at,
        )
